from __future__ import annotations

import csv
import itertools
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict

from ofti.core.case import read_number_of_subdomains
from ofti.core.entry_io import write_entry
from ofti.core.solver_checks import resolve_solver_name, validate_initial_fields
from ofti.core.times import latest_time
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
from ofti.foamlib import runner as foamlib_runner
from ofti.foamlib.adapter import FoamlibUnavailableError
from ofti.foamlib.parametric import (
    build_matrix_cases,
    build_parametric_cases,
    build_parametric_cases_from_csv,
    build_parametric_cases_from_grid,
)
from ofti.tools import knife_service, runner_service
from ofti.tools.helpers import with_bashrc
from ofti.tools.job_registry import register_job
from ofti.tools.tool_catalog import tool_catalog

from .common import require_case_dir

RunResult = runner_service.RunResult


class ToolCatalogPayload(TypedDict):
    case: str
    tools: list[str]


class MatrixAxis(TypedDict):
    dict_path: str
    entry: str
    values: list[str]


class GridAxis(TypedDict):
    dict_path: str
    entry: str
    values: list[str]


def normalize_tool_name(value: str) -> str:
    lowered = value.strip().lower()
    return "".join(ch for ch in lowered if ch.isalnum() or ch in {"-", "_", ".", ":"})


def tool_catalog_names(case_dir: Path) -> list[str]:
    payload = tool_catalog_payload(case_dir)
    return list(payload["tools"])


def tool_catalog_payload(case_dir: Path) -> ToolCatalogPayload:
    case_path = require_case_dir(case_dir)
    names = [name for name, _ in tool_catalog(case_path)]
    return {"case": str(case_path.resolve()), "tools": names}


def write_tool_catalog_json(case_dir: Path, output_path: Path | None = None) -> Path:
    case_path = require_case_dir(case_dir)
    payload = tool_catalog_payload(case_path)
    destination = output_path if output_path is not None else Path(".ofti/tool_catalog.json")
    if not destination.is_absolute():
        destination = case_path / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return destination.resolve()


def resolve_tool(case_dir: Path, name: str) -> tuple[str, list[str]] | None:
    case_path = require_case_dir(case_dir)
    catalog = tool_catalog(case_path)
    for query in _catalog_resolution_queries(name):
        resolved = _resolve_tool_from_catalog(catalog, query)
        if resolved is not None:
            return resolved
    return None


def catalog_command_keys(case_dir: Path) -> list[str]:
    case_path = require_case_dir(case_dir)
    keys: list[str] = []
    for display, _cmd in tool_catalog(case_path):
        normalized = normalize_tool_name(display)
        if normalized:
            keys.append(normalized)
        if not display.startswith("[post] "):
            continue
        token = normalize_tool_name(display.removeprefix("[post] "))
        if not token:
            continue
        keys.append(token)
        keys.append(normalize_tool_name(f"post:{token}"))
        keys.append(normalize_tool_name(f"post.{token}"))
    return sorted(set(keys))


def expand_command(case_dir: Path, cmd: list[str]) -> list[str]:
    case_path = require_case_dir(case_dir)
    latest = latest_time(case_path)
    return [part.replace("{{latestTime}}", latest) for part in cmd]


def solver_command(
    case_dir: Path,
    *,
    solver: str | None = None,
    parallel: int = 0,
    mpi: str | None = None,
    sync_subdomains: bool = True,
) -> tuple[str, list[str]]:
    case_path = require_case_dir(case_dir)
    chosen_solver = solver
    if not chosen_solver:
        chosen_solver, error = resolve_solver_name(case_path)
        if error:
            raise ValueError(f"Cannot resolve solver: {error}")
    if not chosen_solver:
        raise ValueError("Cannot resolve solver from case.")

    errors = validate_initial_fields(case_path)
    if errors:
        raise ValueError("\n".join(errors))

    cmd = [chosen_solver]
    if parallel > 1:
        if sync_subdomains:
            _sync_parallel_subdomains(case_path, requested=parallel)
        else:
            _require_parallel_subdomains(case_path, requested=parallel)
        launcher = mpi or detect_mpi_launcher()
        if not launcher:
            raise ValueError("MPI launcher not found (tried mpirun, mpiexec).")
        cmd = [launcher, "-np", str(parallel), chosen_solver, "-parallel"]
    display = f"{chosen_solver}-parallel" if parallel > 1 else chosen_solver
    return display, cmd


def prepare_parallel_case(
    case_dir: Path,
    *,
    parallel: int,
    clean_processors: bool = False,
    extra_env: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    if parallel <= 1:
        return {
            "parallel": int(parallel),
            "clean_processors": bool(clean_processors),
            "decompose_command": None,
            "cleaned_processors": [],
            "decompose_returncode": None,
            "dry_run": bool(dry_run),
            "applied": False,
        }
    cleaned = _list_processor_dirs(case_path) if clean_processors else []
    decompose_cmd = ["decomposePar", "-force"]
    payload: dict[str, Any] = {
        "parallel": int(parallel),
        "clean_processors": bool(clean_processors),
        "decompose_command": dry_run_command(decompose_cmd),
        "cleaned_processors": [str(path) for path in cleaned],
        "decompose_returncode": None,
        "dry_run": bool(dry_run),
        "applied": not bool(dry_run),
    }
    if dry_run:
        return payload
    if clean_processors:
        _remove_processor_dirs(cleaned)
    result = execute_case_command(
        case_path,
        "decomposePar",
        decompose_cmd,
        background=False,
        extra_env=extra_env,
    )
    payload["decompose_returncode"] = int(result.returncode)
    if int(result.returncode) != 0:
        raise ValueError(_decompose_failure_message(result))
    return payload


def execute_case_command(
    case_dir: Path,
    name: str,
    cmd: list[str],
    *,
    background: bool,
    detached: bool = True,
    log_path: Path | None = None,
    pid_path: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> RunResult:
    case_path = require_case_dir(case_dir)
    return runner_service.execute_case_command(
        case_path,
        name,
        cmd,
        background=background,
        detached=detached,
        log_path=log_path,
        pid_path=pid_path,
        extra_env=extra_env,
        with_bashrc_fn=with_bashrc,
        run_trusted_fn=run_trusted,
        popen_fn=subprocess.Popen,
        register_job_fn=register_job,
    )


def execute_solver_case_command(
    case_dir: Path,
    name: str,
    cmd: list[str],
    *,
    parallel: int = 0,
    mpi: str | None = None,
    background: bool,
    detached: bool = True,
    log_path: Path | None = None,
    pid_path: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> RunResult:
    case_path = require_case_dir(case_dir)
    solver = _solver_token_from_command(cmd, parallel=parallel)
    if _requires_solver_subprocess(
        background=background,
        extra_env=extra_env,
        parallel=parallel,
        mpi=mpi,
        solver=solver,
    ):
        return execute_case_command(
            case_path,
            name,
            cmd,
            background=False,
            detached=detached,
            log_path=log_path,
            pid_path=pid_path,
            extra_env=extra_env,
        )

    assert solver is not None
    chosen_log = _resolve_solver_log_path(case_path, name=name, log_path=log_path)
    try:
        foamlib_runner.run_case(
            case_path,
            solver,
            parallel=parallel > 1,
            cpus=parallel if parallel > 1 else None,
            check=True,
            log=str(chosen_log),
        )
    except Exception as exc:
        if isinstance(exc, FoamlibUnavailableError):
            return execute_case_command(
                case_path,
                name,
                cmd,
                background=False,
                detached=detached,
                log_path=log_path,
                pid_path=pid_path,
                extra_env=extra_env,
            )
        if isinstance(exc, subprocess.CalledProcessError):
            return RunResult(
                int(exc.returncode),
                "",
                f"{exc}\nSee log: {chosen_log}",
                pid=None,
                log_path=chosen_log,
            )
        return RunResult(1, "", f"{exc}\nSee log: {chosen_log}", pid=None, log_path=chosen_log)
    return RunResult(0, "", "", pid=None, log_path=chosen_log)


def dry_run_command(cmd: list[str]) -> str:
    return runner_service.dry_run_command(cmd, with_bashrc_fn=with_bashrc)


def detect_mpi_launcher() -> str | None:
    for candidate in ("mpirun", "mpiexec"):
        try:
            return resolve_executable(candidate)
        except FileNotFoundError:
            continue
    return None


def _sync_parallel_subdomains(case_path: Path, *, requested: int) -> None:
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        raise ValueError(
            "Missing system/decomposeParDict for parallel run. "
            "Create it first or run without --parallel.",
        )
    initial = _read_subdomains_value(decompose_dict)
    if initial == requested:
        return
    write_entry(decompose_dict, "numberOfSubdomains", str(requested))
    updated = _read_subdomains_value(decompose_dict)
    if updated == requested:
        return
    _write_subdomains_fallback(decompose_dict, requested=requested)
    final = _read_subdomains_value(decompose_dict)
    if final == requested:
        return
    configured = final if final is not None else updated if updated is not None else initial
    raise ValueError(_subdomains_sync_error(case_path, requested=requested, configured=configured))


def _require_parallel_subdomains(case_path: Path, *, requested: int) -> None:
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        raise ValueError(
            "Missing system/decomposeParDict for parallel run. "
            "Create it first or run without --parallel.",
        )
    configured = _read_subdomains_value(decompose_dict)
    if configured == requested:
        return
    raise ValueError(
        _subdomains_precheck_error(case_path, requested=requested, configured=configured),
    )


def _read_subdomains_value(decompose_dict: Path) -> int | None:
    configured = read_number_of_subdomains(decompose_dict)
    if configured is not None:
        return configured
    return _read_subdomains_fallback(decompose_dict)


def _subdomains_sync_error(case_path: Path, *, requested: int, configured: int | None) -> str:
    detected = "missing or invalid" if configured is None else str(configured)
    fix_cmd = (
        f"cd {shlex.quote(str(case_path))} && "
        "foamDictionary system/decomposeParDict "
        f"-entry numberOfSubdomains -set {requested}"
    )
    return (
        "Parallel launch blocked: requested "
        f"{requested} ranks but system/decomposeParDict has {detected}. "
        "Automatic sync failed. "
        f"Fix with: {fix_cmd}"
    )


def _subdomains_precheck_error(case_path: Path, *, requested: int, configured: int | None) -> str:
    detected = "missing or invalid" if configured is None else str(configured)
    fix_cmd = (
        f"cd {shlex.quote(str(case_path))} && "
        "foamDictionary system/decomposeParDict "
        f"-entry numberOfSubdomains -set {requested}"
    )
    return (
        "Parallel launch blocked: requested "
        f"{requested} ranks but system/decomposeParDict has {detected}. "
        f"Run with --sync-subdomains or fix manually: {fix_cmd}"
    )


_SUBDOMAINS_RE = re.compile(
    r"(^|\n)(?P<prefix>\s*numberOfSubdomains\s+)(?P<value>[0-9]+)(?P<suffix>\s*;)",
    re.MULTILINE,
)


def _read_subdomains_fallback(decompose_dict: Path) -> int | None:
    try:
        text = decompose_dict.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = _SUBDOMAINS_RE.search(text)
    if match is None:
        return None
    try:
        return int(match.group("value"))
    except ValueError:
        return None


def _write_subdomains_fallback(decompose_dict: Path, *, requested: int) -> bool:
    try:
        text = decompose_dict.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    if _SUBDOMAINS_RE.search(text):
        updated = _SUBDOMAINS_RE.sub(
            lambda m: f"{m.group(1)}{m.group('prefix')}{requested}{m.group('suffix')}",
            text,
            count=1,
        )
    else:
        suffix = "" if text.endswith("\n") else "\n"
        updated = f"{text}{suffix}numberOfSubdomains {requested};\n"
    try:
        decompose_dict.write_text(updated, encoding="utf-8")
    except OSError:
        return False
    return True


def _list_processor_dirs(case_path: Path) -> list[Path]:
    return sorted(
        path
        for path in case_path.iterdir()
        if path.is_dir() and path.name.startswith("processor")
    )


def _remove_processor_dirs(paths: list[Path]) -> None:
    for path in paths:
        try:
            shutil.rmtree(path)
        except OSError as exc:
            raise ValueError(f"Failed to remove stale processor directory {path}: {exc}") from exc


def _decompose_failure_message(result: RunResult) -> str:
    summary = "decomposePar failed before solver launch"
    details = (result.stderr or result.stdout or "").strip()
    if not details:
        return f"{summary} (exit {result.returncode})."
    lines = [line for line in details.splitlines() if line.strip()]
    short = "\n".join(lines[:8])
    return f"{summary} (exit {result.returncode}).\n{short}"


def _resolve_solver_log_path(case_path: Path, *, name: str, log_path: Path | None) -> Path:
    if log_path is not None:
        resolved = log_path if log_path.is_absolute() else case_path / log_path
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved
    safe = runner_service.safe_name(name)
    resolved = case_path / f"log.{safe}"
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _solver_token_from_command(cmd: list[str], *, parallel: int) -> str | None:
    if parallel > 1:
        if len(cmd) >= 2 and cmd[-1] == "-parallel":
            return str(cmd[-2])
        return None
    if len(cmd) == 1:
        return str(cmd[0])
    return None


def _requires_solver_subprocess(
    *,
    background: bool,
    extra_env: dict[str, str] | None,
    parallel: int,
    mpi: str | None,
    solver: str | None,
) -> bool:
    return bool(
        background
        or extra_env
        or (parallel > 1 and mpi)
        or not solver,
    )


def _normalize_name(value: str) -> str:
    return normalize_tool_name(value)


def _catalog_resolution_queries(name: str) -> list[str]:
    normalized = normalize_tool_name(name)
    queries = [name]
    if normalized.startswith("post:"):
        token = normalized.split(":", 1)[1]
        if token:
            queries.append(f"[post] {token}")
    if normalized.startswith("post."):
        token = normalized.split(".", 1)[1]
        if token:
            queries.append(f"[post] {token}")
    return queries


def _resolve_tool_from_catalog(
    catalog: list[tuple[str, list[str]]],
    name: str,
) -> tuple[str, list[str]] | None:
    normalized = normalize_tool_name(name)
    for display, cmd in catalog:
        if display == name or normalize_tool_name(display) == normalized:
            return display, list(cmd)
    return None


def parse_matrix_axes(raw_axes: list[str], *, default_dict: str) -> list[MatrixAxis]:
    axes: list[MatrixAxis] = []
    for spec in raw_axes:
        token = spec.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"invalid matrix axis (expected key=values): {spec}")
        left, right = token.split("=", 1)
        if ":" in left:
            dict_path_raw, entry_raw = left.split(":", 1)
            dict_path = dict_path_raw.strip()
            entry = entry_raw.strip()
        else:
            dict_path = default_dict.strip()
            entry = left.strip()
        values = [value.strip() for value in right.split(",") if value.strip()]
        if not dict_path:
            raise ValueError(f"invalid matrix axis dict path: {spec}")
        if not entry:
            raise ValueError(f"invalid matrix axis entry: {spec}")
        if not values:
            raise ValueError(f"invalid matrix axis values: {spec}")
        axes.append({"dict_path": dict_path, "entry": entry, "values": values})
    if not axes:
        raise ValueError("at least one --param axis is required")
    return axes


def parse_sweep_values(raw_values: list[str]) -> list[str]:
    values: list[str] = []
    for token in raw_values:
        for value in token.split(","):
            item = value.strip()
            if item:
                values.append(item)
    return values


def parse_grid_axes(raw_axes: list[str], *, default_dict: str) -> list[GridAxis]:
    return [
        {
            "dict_path": axis["dict_path"],
            "entry": axis["entry"],
            "values": list(axis["values"]),
        }
        for axis in parse_matrix_axes(raw_axes, default_dict=default_dict)
    ]


def parametric_case_payload(
    case_dir: Path,
    *,
    dict_path: str,
    entry: str | None,
    values: list[str],
    csv_path: Path | None,
    grid_axes: list[GridAxis],
    output_root: Path | None = None,
    run_solver: bool = False,
    solver: str | None = None,
    parallel: int = 0,
    mpi: str | None = None,
    max_parallel: int = 1,
    poll_interval: float = 0.25,
    queue_backend: str = "process",
    prepare_parallel: bool = True,
    clean_processors: bool = False,
) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    mode = _parametric_mode(csv_path, grid_axes)
    root = output_root.resolve() if output_root is not None else case_path.parent.resolve()
    created: list[Path]
    if mode == "csv":
        assert csv_path is not None
        created = build_parametric_cases_from_csv(
            case_path,
            csv_path,
            output_root=root,
        )
    elif mode == "grid":
        created = build_parametric_cases_from_grid(
            case_path,
            list(grid_axes),
            output_root=root,
        )
    else:
        if not entry:
            raise ValueError("--entry is required for single-entry parametric mode")
        if not values:
            raise ValueError("--values is required for single-entry parametric mode")
        created = build_parametric_cases(
            case_path,
            Path(dict_path),
            entry,
            values,
            output_root=root,
        )
    queue_result: dict[str, Any] | None = None
    if run_solver and created:
        queue_result = queue_payload(
            cases=created,
            solver=solver,
            parallel=parallel,
            mpi=mpi,
            max_parallel=max_parallel,
            poll_interval=poll_interval,
            dry_run=False,
            backend=queue_backend,
            prepare_parallel=prepare_parallel,
            clean_processors=clean_processors,
        )
    return {
        "case": str(case_path.resolve()),
        "mode": mode,
        "dict_path": dict_path,
        "entry": entry,
        "values": list(values),
        "csv_path": str(csv_path) if csv_path is not None else None,
        "grid_axes": list(grid_axes),
        "output_root": str(root),
        "created_count": len(created),
        "created": [str(path.resolve()) for path in created],
        "run_solver": run_solver,
        "queue": queue_result,
        "queue_backend": queue_backend,
        "prepare_parallel": bool(prepare_parallel),
        "clean_processors": bool(clean_processors),
    }


def _parametric_mode(csv_path: Path | None, grid_axes: list[GridAxis]) -> str:
    if csv_path is not None and grid_axes:
        raise ValueError("choose only one mode: --csv or --grid-axis")
    if csv_path is not None:
        return "csv"
    if grid_axes:
        return "grid"
    return "single"


def matrix_case_payload(
    case_dir: Path,
    *,
    axes: list[MatrixAxis],
    output_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    template = require_case_dir(case_dir)
    root = output_root.resolve() if output_root is not None else template.parent.resolve()
    combos = matrix_combinations(axes)
    created_rows: list[dict[str, Any]] = []
    for combo in combos:
        destination = root / matrix_case_name(template.name, combo)
        value_map = {_axis_label(axis): value for axis, value in combo}
        row: dict[str, Any] = {
            "case": str(destination.resolve()),
            "values": value_map,
            "created": False,
        }
        if destination.exists():
            raise ValueError(f"destination already exists: {destination}")
        created_rows.append(row)
    if not dry_run:
        build_matrix_cases(
            template,
            [dict(axis) for axis in axes],
            output_root=root,
            case_name_fn=lambda combo: matrix_case_name(template.name, _matrix_combo(combo)),
        )
        for row in created_rows:
            row["created"] = True
    return {
        "template_case": str(template),
        "output_root": str(root),
        "axis_count": len(axes),
        "case_count": len(created_rows),
        "axes": axes,
        "cases": created_rows,
        "dry_run": dry_run,
    }


def queue_payload(
    *,
    cases: list[Path],
    solver: str | None = None,
    parallel: int = 0,
    mpi: str | None = None,
    max_parallel: int = 1,
    poll_interval: float = 0.25,
    dry_run: bool = False,
    backend: str = "process",
    prepare_parallel: bool = True,
    clean_processors: bool = False,
) -> dict[str, Any]:
    if max_parallel <= 0:
        raise ValueError("max_parallel must be > 0")
    if backend not in {"process", "foamlib-async", "foamlib-slurm"}:
        raise ValueError("backend must be one of: process, foamlib-async, foamlib-slurm")
    normalized_cases = [require_case_dir(path) for path in cases]
    plan: list[dict[str, Any]] = []
    for case_path in normalized_cases:
        display, cmd = solver_command(
            case_path,
            solver=solver,
            parallel=parallel,
            mpi=mpi,
        )
        plan.append(
            {
                "case": str(case_path),
                "name": display,
                "command": dry_run_command(cmd),
                "solver_cmd": _solver_token_from_command(cmd, parallel=parallel),
            },
        )
    payload: dict[str, Any] = {
        "count": len(plan),
        "max_parallel": max_parallel,
        "poll_interval": poll_interval,
        "dry_run": dry_run,
        "backend": backend,
        "prepare_parallel": bool(prepare_parallel),
        "clean_processors": bool(clean_processors),
        "planned": plan,
        "started": [],
        "finished": [],
        "failed_to_start": [],
        "ok": True,
    }
    if prepare_parallel and parallel > 1:
        for row in plan:
            row_case = Path(str(row["case"]))
            try:
                row["parallel_setup"] = prepare_parallel_case(
                    row_case,
                    parallel=parallel,
                    clean_processors=clean_processors,
                    dry_run=True,
                )
            except ValueError as exc:
                row["parallel_setup_error"] = str(exc)
    if dry_run:
        return payload
    if backend == "process":
        _queue_process_backend(
            payload,
            plan=plan,
            solver=solver,
            parallel=parallel,
            mpi=mpi,
            poll_interval=poll_interval,
            prepare_parallel=prepare_parallel,
            clean_processors=clean_processors,
        )
    else:
        _queue_foamlib_backend(
            payload,
            plan=plan,
            parallel=parallel,
            max_parallel=max_parallel,
            backend=backend,
            prepare_parallel=prepare_parallel,
            clean_processors=clean_processors,
        )
    return payload


def _queue_process_backend(
    payload: dict[str, Any],
    *,
    plan: list[dict[str, Any]],
    solver: str | None,
    parallel: int,
    mpi: str | None,
    poll_interval: float,
    prepare_parallel: bool,
    clean_processors: bool,
) -> None:
    pending = list(plan)
    active: list[dict[str, Any]] = []
    while pending or active:
        while pending and len(active) < int(payload["max_parallel"]):
            row = pending.pop(0)
            case_path = Path(str(row["case"]))
            # Rebuild command from current case to avoid stale snapshots.
            name, command = solver_command(
                case_path,
                solver=solver,
                parallel=parallel,
                mpi=mpi,
            )
            if parallel > 1 and "-parallel" in command and prepare_parallel:
                try:
                    prepare_parallel_case(
                        case_path,
                        parallel=parallel,
                        clean_processors=clean_processors,
                        dry_run=False,
                    )
                except ValueError as exc:
                    payload["failed_to_start"].append({"case": str(case_path), "error": str(exc)})
                    payload["ok"] = False
                    continue
            try:
                result = execute_case_command(
                    case_path,
                    name,
                    command,
                    background=True,
                    detached=True,
                )
            except ValueError as exc:
                payload["failed_to_start"].append({"case": str(case_path), "error": str(exc)})
                payload["ok"] = False
                continue
            if result.pid is None:
                payload["failed_to_start"].append(
                    {"case": str(case_path), "error": "missing background pid"},
                )
                payload["ok"] = False
                continue
            started = {
                "case": str(case_path),
                "pid": int(result.pid),
                "name": name,
                "log_path": str(result.log_path) if result.log_path is not None else "",
                "started_at": time.time(),
            }
            active.append(started)
            payload["started"].append(started)
        if not active:
            break
        time.sleep(max(0.05, poll_interval))
        still_active: list[dict[str, Any]] = []
        for row in active:
            pid = int(row["pid"])
            if _pid_running(pid):
                still_active.append(row)
                continue
            status_row = status_row_payload(Path(str(row["case"])))
            payload["finished"].append(
                {
                    "case": row["case"],
                    "pid": pid,
                    "state": status_row["state"],
                    "stop_reason": status_row["stop_reason"],
                    "latest_time": status_row["latest_time"],
                    "eta_seconds": status_row["eta_seconds"],
                },
            )
        active = still_active


def _queue_foamlib_backend(
    payload: dict[str, Any],
    *,
    plan: list[dict[str, Any]],
    parallel: int,
    max_parallel: int,
    backend: str,
    prepare_parallel: bool,
    clean_processors: bool,
) -> None:
    by_solver, ready_cases = _queue_collect_foamlib_cases(
        payload,
        plan=plan,
        parallel=parallel,
        prepare_parallel=prepare_parallel,
        clean_processors=clean_processors,
    )
    for solver_cmd, case_group in by_solver.items():
        failures, error = _queue_run_foamlib_group(
            case_group,
            solver_cmd=solver_cmd,
            parallel=parallel,
            max_parallel=max_parallel,
            backend=backend,
        )
        if error is not None:
            for case_path in case_group:
                payload["failed_to_start"].append({"case": str(case_path), "error": str(error)})
            payload["ok"] = False
            continue
        failed_map = {str(path.resolve()) for path in failures}
        _queue_append_foamlib_finished(payload, case_group=case_group, failed_map=failed_map)
    _queue_fill_foamlib_missing_finished(payload, ready_cases=ready_cases)


def _queue_collect_foamlib_cases(
    payload: dict[str, Any],
    *,
    plan: list[dict[str, Any]],
    parallel: int,
    prepare_parallel: bool,
    clean_processors: bool,
) -> tuple[dict[str, list[Path]], list[Path]]:
    by_solver: dict[str, list[Path]] = {}
    ready_cases: list[Path] = []
    for row in plan:
        case_path = Path(str(row["case"]))
        solver_cmd = str(row.get("solver_cmd") or "").strip()
        if not solver_cmd:
            payload["failed_to_start"].append(
                {
                    "case": str(case_path),
                    "error": "unable to resolve solver command for foamlib backend",
                },
            )
            payload["ok"] = False
            continue
        if prepare_parallel and parallel > 1:
            try:
                prepare_parallel_case(
                    case_path,
                    parallel=parallel,
                    clean_processors=clean_processors,
                    dry_run=False,
                )
            except ValueError as exc:
                payload["failed_to_start"].append({"case": str(case_path), "error": str(exc)})
                payload["ok"] = False
                continue
        by_solver.setdefault(solver_cmd, []).append(case_path)
        ready_cases.append(case_path)
        payload["started"].append(
            {
                "case": str(case_path),
                "pid": None,
                "name": str(row.get("name") or solver_cmd),
                "log_path": "",
                "started_at": time.time(),
            },
        )
    return by_solver, ready_cases


def _queue_run_foamlib_group(
    case_group: list[Path],
    *,
    solver_cmd: str,
    parallel: int,
    max_parallel: int,
    backend: str,
) -> tuple[list[Path], Exception | None]:
    try:
        failures = foamlib_runner.run_cases_async(
            case_group,
            cmd=solver_cmd,
            parallel=parallel > 1,
            cpus=parallel if parallel > 1 else None,
            check=False,
            log=True,
            max_parallel=max_parallel,
            slurm=backend == "foamlib-slurm",
            fallback=True,
        )
    except Exception as exc:
        return [], exc
    return failures, None


def _queue_append_foamlib_finished(
    payload: dict[str, Any],
    *,
    case_group: list[Path],
    failed_map: set[str],
) -> None:
    for case_path in case_group:
        status_row = status_row_payload(case_path)
        row: dict[str, Any] = {
            "case": str(case_path),
            "pid": None,
            "state": status_row["state"],
            "stop_reason": status_row["stop_reason"],
            "latest_time": status_row["latest_time"],
            "eta_seconds": status_row["eta_seconds"],
        }
        payload["finished"].append(row)
        if str(case_path.resolve()) in failed_map:
            payload["ok"] = False


def _queue_fill_foamlib_missing_finished(
    payload: dict[str, Any],
    *,
    ready_cases: list[Path],
) -> None:
    finished_cases = {str(Path(str(row["case"])).resolve()) for row in payload["finished"]}
    for case_path in ready_cases:
        key = str(case_path.resolve())
        if key in finished_cases:
            continue
        payload["finished"].append(
            {
                "case": str(case_path),
                "pid": None,
                "state": "unknown",
                "stop_reason": "not finished",
                "latest_time": None,
                "eta_seconds": None,
            },
        )


def status_set_payload(
    *,
    set_dir: Path,
    explicit_cases: list[Path],
    case_glob: str = "*",
    summary_csv: Path | None = None,
    lightweight: bool = True,
    tail_bytes: int | None = None,
) -> dict[str, Any]:
    root = require_case_dir(set_dir)
    cases = resolve_case_set(
        set_dir=root,
        explicit_cases=explicit_cases,
        case_glob=case_glob,
        summary_csv=summary_csv,
    )
    rows = [
        status_row_payload(
            case_path,
            lightweight=lightweight,
            tail_bytes=tail_bytes,
        )
        for case_path in cases
    ]
    return {
        "set_dir": str(root),
        "glob": case_glob,
        "summary_csv": str(summary_csv.resolve()) if summary_csv is not None else None,
        "count": len(rows),
        "rows": rows,
    }


def resolve_case_set(
    *,
    set_dir: Path,
    explicit_cases: list[Path],
    case_glob: str,
    summary_csv: Path | None,
) -> list[Path]:
    root = require_case_dir(set_dir)
    rows: list[Path] = []
    if explicit_cases:
        rows = [require_case_dir(case) for case in explicit_cases]
    elif summary_csv is not None:
        summary_path = summary_csv.expanduser()
        if not summary_path.is_absolute():
            summary_path = root / summary_path
        rows = _cases_from_summary_csv(root, summary_path.resolve())
    else:
        pattern = case_glob.strip() or "*"
        rows = [
            path.resolve()
            for path in root.glob(pattern)
            if path.is_dir() and (path / "system" / "controlDict").is_file()
        ]
    unique_map: dict[str, Path] = {}
    for path in rows:
        resolved = path.resolve()
        unique_map[str(resolved)] = resolved
    ordered = [unique_map[key] for key in sorted(unique_map)]
    return [path for path in ordered if (path / "system" / "controlDict").is_file()]


def status_row_payload(
    case_path: Path,
    *,
    lightweight: bool = True,
    tail_bytes: int | None = None,
) -> dict[str, Any]:
    payload = knife_service.status_payload(
        case_path,
        lightweight=lightweight,
        tail_bytes=tail_bytes,
    )
    state = _case_state(payload)
    reason = _stop_reason(payload, state=state)
    return {
        "case": str(case_path.resolve()),
        "state": state,
        "latest_time": payload.get("latest_time"),
        "eta_seconds": payload.get("eta_seconds_to_end_time"),
        "stop_reason": reason,
        "jobs_running": payload.get("jobs_running", 0),
    }


def matrix_combinations(axes: list[MatrixAxis]) -> list[list[tuple[MatrixAxis, str]]]:
    value_sets = [axis["values"] for axis in axes]
    combos: list[list[tuple[MatrixAxis, str]]] = []
    for values in itertools.product(*value_sets):
        combo = list(zip(axes, values, strict=True))
        combos.append(combo)
    return combos


def matrix_case_name(template_name: str, combo: list[tuple[MatrixAxis, str]]) -> str:
    tokens = [template_name]
    for axis, value in combo:
        entry_token = _sanitize_token(_axis_label(axis).replace(".", "_").replace("/", "_"))
        value_token = _sanitize_token(value)
        tokens.append(f"{entry_token}-{value_token}")
    return "__".join(tokens)


def _axis_label(axis: MatrixAxis) -> str:
    return f"{axis['dict_path']}:{axis['entry']}"


def _sanitize_token(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "value"


def _cases_from_summary_csv(root: Path, summary_csv: Path) -> list[Path]:
    rows: list[Path] = []
    try:
        with summary_csv.open("r", encoding="utf-8", errors="ignore") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                raw = (
                    str(row.get("case") or "")
                    or str(row.get("case_dir") or "")
                    or str(row.get("path") or "")
                    or str(row.get("dir") or "")
                ).strip()
                if not raw:
                    continue
                path = Path(raw).expanduser()
                if not path.is_absolute():
                    path = root / path
                rows.append(path.resolve())
    except OSError:
        return []
    return rows


def _matrix_combo(
    combo: list[tuple[dict[str, Any], str]],
) -> list[tuple[MatrixAxis, str]]:
    result: list[tuple[MatrixAxis, str]] = []
    for axis, value in combo:
        result.append(
            (
                {
                    "dict_path": str(axis["dict_path"]),
                    "entry": str(axis["entry"]),
                    "values": [str(item) for item in axis.get("values", [])],
                },
                value,
            ),
        )
    return result


def _case_state(payload: Mapping[str, Any]) -> str:
    if bool(payload.get("running")):
        return "running"
    if payload.get("solver_error"):
        return "error"
    rtc = payload.get("run_time_control", {})
    if int(rtc.get("failed", 0)) > 0:
        return "failed"
    latest_time = payload.get("latest_time")
    end_time = rtc.get("end_time")
    if (
        isinstance(latest_time, (int, float))
        and isinstance(end_time, (int, float))
        and latest_time >= end_time
    ):
        return "done"
    if bool(payload.get("log_fresh")):
        return "recent"
    return "stopped"


def _stop_reason(payload: Mapping[str, Any], *, state: str) -> str:
    if state == "running":
        return ""
    solver_error = payload.get("solver_error")
    if isinstance(solver_error, str) and solver_error:
        return solver_error
    rtc = payload.get("run_time_control", {})
    criteria = rtc.get("criteria", [])
    if isinstance(criteria, list):
        for row in criteria:
            if str(row.get("status")) == "pass":
                continue
            reason = str(row.get("unmet_reason") or "").strip()
            if reason:
                return reason
    latest_time = payload.get("latest_time")
    end_time = rtc.get("end_time")
    if (
        isinstance(latest_time, (int, float))
        and isinstance(end_time, (int, float))
        and latest_time >= end_time
    ):
        return "end_time_reached"
    if state == "failed":
        return "criteria_failed"
    return "stopped"


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
