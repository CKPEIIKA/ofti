"""Bounded solver smoke-test payloads (extracted from cli_tools.run).

Execution helpers (solver_command, prepare_parallel_case, dry_run_command) stay
in cli_tools.run and are reached via the lazy ``_run()`` accessor so they remain
patchable and avoid an import cycle.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from contextlib import suppress
from difflib import unified_diff
from pathlib import Path
from typing import Any

from ofti.core.checkpoint import checkpoint_health
from ofti.core.entry_io import read_entry, write_entry_preserving_text
from ofti.core.field_io import read_internal_field, resolve_field_names, resolve_time_dir
from ofti.core.times import processor_dirs
from ofti.tools import knife_service, runner_service

from .common import require_case_dir

_TIME_RE = re.compile(r"^\s*Time\s*=\s*(?P<time>[-+0-9.eE]+)\s*$", re.MULTILINE)


def _run() -> Any:
    from ofti.tools.cli_tools import run

    return run


def smoke_payload(
    case_dir: Path,
    *,
    solver: str | None = None,
    iterations: int = 20,
    timeout: float = 300.0,
    parallel: int = 0,
    mpi: str | None = None,
    output_root: Path | None = None,
    in_place: bool = False,
    delta_t: float | None = None,
    preserve_delta_t: bool = False,
    core_only: bool = False,
    prepare_parallel: bool = True,
    clean_processors: bool = False,
    reconstruct: bool = False,
    run_physical: bool = False,
    physical_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Run a bounded solver smoke test on a copied case by default."""
    if iterations <= 0:
        raise ValueError("iterations must be > 0")
    if timeout <= 0:
        raise ValueError("timeout must be > 0")
    source = require_case_dir(case_dir)
    root = _smoke_output_root(source, output_root=output_root)
    smoke_case = source if in_place else root / "case"
    if not in_place:
        if smoke_case.exists():
            raise ValueError(f"smoke output case already exists: {smoke_case}")
        shutil.copytree(source, smoke_case, ignore=shutil.ignore_patterns(".ofti"))
    else:
        root.mkdir(parents=True, exist_ok=True)
    control = smoke_case / "system" / "controlDict"
    chosen_delta_t = _smoke_delta_t(control, delta_t=delta_t, preserve_delta_t=preserve_delta_t)
    normalized = _normalize_smoke_control_dict(
        control,
        iterations=iterations,
        delta_t=chosen_delta_t,
        preserve_delta_t=preserve_delta_t,
        core_only=core_only,
    )
    chosen_solver = solver or _read_control_word(control, "application")
    display, command = _run().solver_command(
        smoke_case,
        solver=chosen_solver,
        parallel=parallel,
        mpi=mpi,
    )
    parallel_setup: dict[str, Any] | None = None
    if parallel > 1 and prepare_parallel:
        parallel_setup = _run().prepare_parallel_case(
            smoke_case,
            parallel=parallel,
            clean_processors=clean_processors,
            dry_run=False,
        )
    started = time.time()
    log_path = root / f"log.{runner_service.safe_name(display)}"
    result, timed_out = _run_smoke_command(
        smoke_case,
        command,
        timeout=timeout,
        log_path=log_path,
    )
    wall_seconds = time.time() - started
    log_text = log_path.read_text(encoding="utf-8", errors="ignore") if log_path.is_file() else ""
    reconstruction = _smoke_reconstruction(
        smoke_case,
        log_text,
        parallel=parallel,
        requested=reconstruct,
    )
    verification = _smoke_verification(
        smoke_case,
        log_text,
        iterations=iterations,
        delta_t=chosen_delta_t,
        parallel=parallel,
        returncode=int(result.returncode),
        timed_out=timed_out,
        reconstruction=reconstruction,
    )
    summary: dict[str, Any] = {
        "source_case": str(source.resolve()),
        "case": str(smoke_case.resolve()),
        "output_root": str(root.resolve()),
        "copied": not in_place,
        "solver": display,
        "command": _run().dry_run_command(command),
        "iterations_requested": int(iterations),
        "timeout_seconds": float(timeout),
        "parallel": int(parallel),
        "prepare_parallel": bool(prepare_parallel),
        "clean_processors": bool(clean_processors),
        "parallel_setup": parallel_setup,
        "reconstruction": reconstruction,
        "normalized_control": normalized,
        "returncode": int(result.returncode),
        "timed_out": bool(timed_out),
        "wall_seconds": wall_seconds,
        "log_path": str(log_path.resolve()),
        **verification,
    }
    if run_physical:
        summary["physical"] = knife_service.physical_payload(
            smoke_case,
            time_name="latest",
            fields=physical_fields,
            out_dir=root,
        )
    _write_smoke_reports(summary, root)
    return summary


def parse_duration_seconds(value: str | float | int) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    match = re.fullmatch(r"(?P<num>[0-9]+(?:\.[0-9]+)?)(?P<unit>ms|s|m|h)?", text)
    if match is None:
        raise ValueError(f"invalid duration: {value}")
    number = float(match.group("num"))
    unit = match.group("unit") or "s"
    factors = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return number * factors[unit]


def _smoke_output_root(source: Path, *, output_root: Path | None) -> Path:
    if output_root is not None:
        return output_root.expanduser().resolve()
    return (source / ".ofti" / "smoke" / f"smoke-{int(time.time())}").resolve()


def _smoke_delta_t(
    control: Path,
    *,
    delta_t: float | None,
    preserve_delta_t: bool,
) -> float:
    if delta_t is not None:
        return float(delta_t)
    raw = _read_control_scalar(control, "deltaT")
    if raw is not None:
        return raw
    if preserve_delta_t:
        raise ValueError("controlDict has no deltaT to preserve")
    return 1.0


def _normalize_smoke_control_dict(
    control: Path,
    *,
    iterations: int,
    delta_t: float,
    preserve_delta_t: bool,
    core_only: bool,
) -> dict[str, Any]:
    before = control.read_text(encoding="utf-8")
    writes = {
        "startFrom": "startTime",
        "startTime": "0",
        "stopAt": "endTime",
        "endTime": f"{iterations * delta_t:g}",
        "writeControl": "timeStep",
        "writeInterval": str(iterations),
        "adjustTimeStep": "false",
        "runTimeModifiable": "false",
    }
    if not preserve_delta_t:
        writes["deltaT"] = f"{delta_t:g}"
    if core_only:
        writes["functions"] = "{}"
    applied = {key: value for key, value in writes.items() if write_entry_preserving_text(control, key, value)}
    required = set(writes).difference({"functions"})
    failed = sorted(required.difference(applied))
    if failed:
        raise ValueError(f"failed to normalize smoke controlDict entries: {', '.join(failed)}")
    after = control.read_text(encoding="utf-8")
    return {
        "controlDict": str(control),
        "deltaT": delta_t,
        "entries": applied,
        "core_only": bool(core_only),
        "text_preserving": True,
        "diff": "".join(
            unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="controlDict.before",
                tofile="controlDict.smoke",
            ),
        ),
    }


def _read_control_scalar(control: Path, key: str) -> float | None:
    try:
        raw = read_entry(control, key)
    except Exception:
        raw = _read_control_scalar_fallback(control, key)
    if raw is None:
        return None
    try:
        return float(str(raw).strip().rstrip(";"))
    except ValueError:
        return None


def _read_control_scalar_fallback(control: Path, key: str) -> str | None:
    try:
        text = control.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(rf"(^|\n)\s*{re.escape(key)}\s+(?P<value>[^;]+);", text)
    return match.group("value").strip() if match else None


def _read_control_word(control: Path, key: str) -> str | None:
    try:
        raw = read_entry(control, key)
    except Exception:
        raw = _read_control_scalar_fallback(control, key)
    token = str(raw or "").strip().rstrip(";").split()
    return token[0] if token else None


def _run_smoke_command(
    case_path: Path,
    command: list[str],
    *,
    timeout: float,
    log_path: Path,
) -> tuple[subprocess.CompletedProcess[str], bool]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    try:
        # Command is built by solver_command(), not shell text; timeout keeps smoke runs bounded.
        # Solver command is built by the trusted command builder and runs without a shell.
        result = subprocess.run(  # noqa: S603
            command,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = _timeout_text(exc.stdout)
        stderr = _timeout_text(exc.stderr)
        result = subprocess.CompletedProcess(command, 124, stdout, stderr)
        timed_out = True
    log_path.write_text(
        f"{result.stdout or ''}{result.stderr or ''}",
        encoding="utf-8",
        errors="ignore",
    )
    return result, timed_out


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return value


def _smoke_times_seen(log_text: str) -> list[float]:
    values: list[float] = []
    for match in _TIME_RE.finditer(log_text):
        with suppress(ValueError):
            values.append(float(match.group("time")))
    return values


def _smoke_verification(
    case_path: Path,
    log_text: str,
    *,
    iterations: int,
    delta_t: float,
    parallel: int,
    returncode: int,
    timed_out: bool,
    reconstruction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    times_seen = _smoke_times_seen(log_text)
    completed = len(times_seen)
    end_seen = _smoke_end_seen(log_text)
    iteration_count_exact = completed == iterations
    target_time = iterations * delta_t
    target_time_reached = bool(times_seen) and _same_time(times_seen[-1], target_time)
    checkpoint = _smoke_checkpoint_evidence(
        case_path, parallel=parallel, final_time=times_seen[-1] if times_seen else None
    )
    readability = _smoke_output_readability(
        case_path,
        time_name=checkpoint["checkpoint_time"],
        parallel=parallel,
    )
    clean_exit = returncode == 0 and not timed_out and end_seen
    reconstruction_required = bool(reconstruction and reconstruction["requested"])
    reconstruction_ok = not reconstruction_required or bool(reconstruction["ok"])
    failures = _smoke_failure_reasons(
        returncode=returncode,
        timed_out=timed_out,
        end_seen=end_seen,
        iteration_count_exact=iteration_count_exact,
        target_time_reached=target_time_reached,
        checkpoint_ok=bool(checkpoint["checkpoint_ok"]),
        output_readable=bool(readability["output_readable"]),
        reconstruction_ok=reconstruction_ok,
    )
    contract_failed = (
        not iteration_count_exact
        or not target_time_reached
        or not checkpoint["checkpoint_ok"]
        or not readability["output_readable"]
        or not reconstruction_ok
    )
    failure_reason = (
        "requested_iterations_or_common_checkpoint_not_reached"
        if contract_failed
        else (failures[0] if failures else None)
    )
    return {
        "times_seen": times_seen,
        "iterations_completed": completed,
        "requested_iterations_reached": completed >= iterations,
        "iteration_count_exact": iteration_count_exact,
        "target_time": target_time,
        "target_time_reached": target_time_reached,
        "end_seen": end_seen,
        "clean_exit": clean_exit,
        "checkpoint_required": True,
        **checkpoint,
        **readability,
        "reconstruction_requested": reconstruction_required,
        "reconstruction_ok": reconstruction["ok"] if reconstruction_required else None,
        "failure_reason": failure_reason,
        "failure_reasons": failures,
        "ok": not failures,
    }


def _smoke_checkpoint_evidence(case_path: Path, *, parallel: int, final_time: float | None) -> dict[str, Any]:
    try:
        health = checkpoint_health(case_path, expected_processors=parallel if parallel > 1 else None)
    except ValueError as exc:
        return {
            "checkpoint_ok": False,
            "checkpoint_error": str(exc),
            "checkpoint_time": None,
            "latest_complete_processor_time": None,
            "latest_written_time": None,
            "checkpoint": None,
        }
    time_names = health["complete_times"] if parallel > 1 else health["reconstructed_times"]
    matched = _matching_time(time_names, final_time)
    return {
        "checkpoint_ok": matched is not None and final_time is not None and final_time > 0,
        "checkpoint_error": None,
        "checkpoint_time": matched,
        "latest_complete_processor_time": health["latest_complete_time"] if parallel > 1 else None,
        "latest_written_time": health["latest_complete_time"] if parallel > 1 else health["latest_reconstructed_time"],
        "checkpoint": health,
    }


def _matching_time(time_names: list[str], final_time: float | None) -> str | None:
    if final_time is None:
        return None
    for time_name in reversed(time_names):
        with suppress(ValueError):
            if _same_time(float(time_name), final_time):
                return time_name
    return None


def _same_time(left: float, right: float) -> bool:
    tolerance = max(1e-30, max(abs(left), abs(right)) * 1e-9)
    return abs(left - right) <= tolerance


def _smoke_end_seen(log_text: str) -> bool:
    return any(line.strip() == "End" for line in log_text.splitlines())


def _smoke_output_readability(
    case_path: Path,
    *,
    time_name: object,
    parallel: int,
) -> dict[str, Any]:
    if not isinstance(time_name, str) or not time_name:
        return {
            "output_readable": False,
            "readable_fields": [],
            "output_read_errors": ["no matching checkpoint time"],
        }
    try:
        time_dir = _checkpoint_time_dir(case_path, time_name, parallel=parallel)
        field_names = resolve_field_names(time_dir, None)
    except (OSError, ValueError) as exc:
        return {
            "output_readable": False,
            "readable_fields": [],
            "output_read_errors": [str(exc)],
        }
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for field_name in field_names:
        try:
            field = read_internal_field(time_dir / field_name)
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"{field_name}: {exc}")
            continue
        rows.append(
            {
                "field": field_name,
                "kind": field.kind,
                "count": field.count,
                "components": field.component_count,
            },
        )
    if not field_names:
        errors.append(f"no readable OpenFOAM fields at time {time_name}")
    return {
        "output_readable": bool(rows) and not errors,
        "readable_fields": rows,
        "output_read_errors": errors,
    }


def _checkpoint_time_dir(case_path: Path, time_name: str, *, parallel: int) -> Path:
    if parallel <= 1:
        return resolve_time_dir(case_path, time_name)
    processors = processor_dirs(case_path)
    if len(processors) != parallel:
        raise ValueError(f"expected {parallel} processor directories, found {len(processors)}")
    time_dir = processors[0] / time_name
    if not time_dir.is_dir():
        raise ValueError(f"processor checkpoint not found: {time_name}")
    return time_dir


def _smoke_reconstruction(
    case_path: Path,
    log_text: str,
    *,
    parallel: int,
    requested: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "requested": requested,
        "ok": None,
        "time": None,
        "command": None,
        "returncode": None,
        "error": None,
    }
    if not requested:
        return payload
    times_seen = _smoke_times_seen(log_text)
    final_time = times_seen[-1] if times_seen else None
    try:
        health = checkpoint_health(
            case_path,
            expected_processors=parallel if parallel > 1 else None,
        )
    except ValueError as exc:
        payload.update(ok=False, error=str(exc))
        return payload
    time_names = health["complete_times"] if parallel > 1 else health["reconstructed_times"]
    time_name = _matching_time(time_names, final_time)
    payload["time"] = time_name
    if time_name is None or final_time is None or final_time <= 0:
        payload.update(ok=False, error="no nonzero complete checkpoint to reconstruct")
        return payload
    if parallel <= 1:
        readable = _smoke_output_readability(case_path, time_name=time_name, parallel=0)
        payload.update(ok=readable["output_readable"], output=readable)
        return payload
    command = ["reconstructPar", "-time", time_name]
    payload["command"] = command
    result = _run().execute_case_command(
        case_path,
        " ".join(command),
        command,
        background=False,
    )
    payload["returncode"] = int(result.returncode)
    if int(result.returncode) != 0:
        payload.update(
            ok=False,
            error=result.stderr or result.stdout or "reconstructPar failed",
        )
        return payload
    readable = _smoke_output_readability(case_path, time_name=time_name, parallel=0)
    payload.update(
        ok=readable["output_readable"],
        error=None if readable["output_readable"] else "reconstructed output is unreadable",
        output=readable,
    )
    return payload


def _smoke_failure_reasons(
    *,
    returncode: int,
    timed_out: bool,
    end_seen: bool,
    iteration_count_exact: bool,
    target_time_reached: bool,
    checkpoint_ok: bool,
    output_readable: bool,
    reconstruction_ok: bool,
) -> list[str]:
    checks = (
        (returncode != 0, "solver_returncode_nonzero"),
        (timed_out, "solver_timeout"),
        (not end_seen, "solver_end_not_seen"),
        (not iteration_count_exact, "requested_iteration_count_not_met"),
        (not target_time_reached, "fixed_step_target_time_not_reached"),
        (not checkpoint_ok, "common_checkpoint_not_written"),
        (not output_readable, "checkpoint_output_unreadable"),
        (not reconstruction_ok, "checkpoint_reconstruction_failed"),
    )
    return [reason for failed, reason in checks if failed]


def _write_smoke_reports(payload: Mapping[str, Any], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        "# OFTI Smoke Run",
        "",
        f"- case: {payload.get('case')}",
        f"- solver: {payload.get('solver')}",
        f"- ok: {payload.get('ok')}",
        f"- returncode: {payload.get('returncode')}",
        f"- timed_out: {payload.get('timed_out')}",
        f"- iterations: {payload.get('iterations_completed')}/{payload.get('iterations_requested')}",
        f"- clean_exit: {payload.get('clean_exit')}",
        f"- checkpoint_ok: {payload.get('checkpoint_ok')}",
        f"- output_readable: {payload.get('output_readable')}",
        f"- reconstruction_ok: {payload.get('reconstruction_ok')}",
        f"- latest_written_time: {payload.get('latest_written_time')}",
        f"- failure_reason: {payload.get('failure_reason')}",
        f"- wall_seconds: {float(payload.get('wall_seconds') or 0):.3f}",
        f"- log: {payload.get('log_path')}",
    ]
    (root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
