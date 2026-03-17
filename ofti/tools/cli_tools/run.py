from __future__ import annotations

import csv
import itertools
import json
import os
import re
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict

from ofti.core.case import read_number_of_subdomains
from ofti.core.case_copy import copy_case_directory
from ofti.core.entry_io import write_entry
from ofti.core.solver_checks import resolve_solver_name, validate_initial_fields
from ofti.foam import openfoam
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
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
    normalized = _normalize_name(name)
    for display, cmd in catalog:
        if display == name or _normalize_name(display) == normalized:
            return display, list(cmd)
    return None


def solver_command(
    case_dir: Path,
    *,
    solver: str | None = None,
    parallel: int = 0,
    mpi: str | None = None,
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
        _sync_parallel_subdomains(case_path, requested=parallel)
        launcher = mpi or detect_mpi_launcher()
        if not launcher:
            raise ValueError("MPI launcher not found (tried mpirun, mpiexec).")
        cmd = [launcher, "-np", str(parallel), chosen_solver, "-parallel"]
    display = f"{chosen_solver}-parallel" if parallel > 1 else chosen_solver
    return display, cmd


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
    configured = read_number_of_subdomains(decompose_dict)
    if configured is None:
        configured = _read_subdomains_fallback(decompose_dict)
    if configured == requested:
        return
    if write_entry(decompose_dict, "numberOfSubdomains", str(requested)):
        return
    if _write_subdomains_fallback(decompose_dict, requested=requested):
        return
    if configured is None:
        raise ValueError(
            "numberOfSubdomains missing or invalid in system/decomposeParDict, "
            f"and automatic update to {requested} failed.",
        )
    raise ValueError(
        "decomposeParDict specifies "
        f"{configured} processors, requested {requested}, "
        "and automatic update failed.",
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


def _normalize_name(value: str) -> str:
    lowered = value.strip().lower()
    return "".join(ch for ch in lowered if ch.isalnum() or ch in {"-", "_", ".", ":"})


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
        if not dry_run:
            _create_matrix_case(template, destination, combo)
            row["created"] = True
        created_rows.append(row)
    return {
        "template_case": str(template),
        "output_root": str(root),
        "axis_count": len(axes),
        "case_count": len(created_rows),
        "axes": axes,
        "cases": created_rows,
        "dry_run": dry_run,
    }


def queue_payload(  # noqa: C901
    *,
    cases: list[Path],
    solver: str | None = None,
    parallel: int = 0,
    mpi: str | None = None,
    max_parallel: int = 1,
    poll_interval: float = 0.25,
    dry_run: bool = False,
) -> dict[str, Any]:
    if max_parallel <= 0:
        raise ValueError("max_parallel must be > 0")
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
            },
        )
    payload: dict[str, Any] = {
        "count": len(plan),
        "max_parallel": max_parallel,
        "poll_interval": poll_interval,
        "dry_run": dry_run,
        "planned": plan,
        "started": [],
        "finished": [],
        "failed_to_start": [],
        "ok": True,
    }
    if dry_run:
        return payload

    pending = list(plan)
    active: list[dict[str, Any]] = []
    while pending or active:
        while pending and len(active) < max_parallel:
            row = pending.pop(0)
            case_path = Path(str(row["case"]))
            # Rebuild command from current case to avoid stale snapshots.
            name, command = solver_command(
                case_path,
                solver=solver,
                parallel=parallel,
                mpi=mpi,
            )
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
    return payload


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


def _create_matrix_case(
    template_case: Path,
    destination: Path,
    combo: list[tuple[MatrixAxis, str]],
) -> None:
    copy_case_directory(
        template_case,
        destination,
        include_runtime_artifacts=False,
        drop_mesh=False,
        keep_zero_directory=True,
    )
    for axis, value in combo:
        dict_path = destination / axis["dict_path"]
        if not dict_path.is_file():
            raise ValueError(f"dictionary not found in generated case: {dict_path}")
        if write_entry(dict_path, axis["entry"], value):
            continue
        if openfoam.write_entry(dict_path, axis["entry"], value):
            continue
        raise ValueError(f"failed to set {axis['entry']} in {dict_path}")


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
