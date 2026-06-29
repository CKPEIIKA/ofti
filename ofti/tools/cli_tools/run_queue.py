"""Case-set run queue payloads (extracted from cli_tools.run).

Execution helpers (solver_command, execute_case_command,
execute_solver_case_command, prepare_parallel_case, dry_run_command,
status_row_payload) stay in cli_tools.run and are reached via the lazy
``_run()`` accessor so they remain patchable and avoid an import cycle.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from ofti.foamlib import runner as foamlib_runner
from ofti.tools import runner_service

from .common import require_case_dir

QUEUE_FORMAT = "ofti.queue-record"
QUEUE_FORMAT_VERSION = 1


def _run() -> Any:
    from ofti.tools.cli_tools import run

    return run


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
    queue_root: Path | None = None,
) -> dict[str, Any]:
    _validate_queue_options(max_parallel=max_parallel, backend=backend)
    normalized_cases = [require_case_dir(path) for path in cases]
    plan = _queue_plan(normalized_cases, solver=solver, parallel=parallel, mpi=mpi)
    payload = _queue_payload_init(
        plan=plan,
        normalized_cases=normalized_cases,
        max_parallel=max_parallel,
        parallel=parallel,
        poll_interval=poll_interval,
        dry_run=dry_run,
        backend=backend,
        prepare_parallel=prepare_parallel,
        clean_processors=clean_processors,
        queue_root=queue_root,
    )
    _queue_plan_parallel_setup(
        plan,
        parallel=parallel,
        prepare_parallel=prepare_parallel,
        clean_processors=clean_processors,
    )
    _queue_write_record(payload)
    if dry_run:
        return payload
    _run_queue_backend(
        payload,
        plan=plan,
        solver=solver,
        parallel=parallel,
        mpi=mpi,
        max_parallel=max_parallel,
        poll_interval=poll_interval,
        backend=backend,
        prepare_parallel=prepare_parallel,
        clean_processors=clean_processors,
    )
    _queue_mark_complete(payload)
    return payload


def _validate_queue_options(*, max_parallel: int, backend: str) -> None:
    if max_parallel <= 0:
        raise ValueError("max_parallel must be > 0")
    if backend not in {"process", "foamlib-async", "foamlib-slurm"}:
        raise ValueError("backend must be one of: process, foamlib-async, foamlib-slurm")


def _queue_plan(
    cases: list[Path],
    *,
    solver: str | None,
    parallel: int,
    mpi: str | None,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for case_path in cases:
        display, cmd = _run().solver_command(case_path, solver=solver, parallel=parallel, mpi=mpi)
        plan.append(
            {
                "case": str(case_path),
                "name": display,
                "command": _run().dry_run_command(cmd),
                "solver_cmd": _run()._solver_token_from_command(cmd, parallel=parallel),
            },
        )
    return plan


def _queue_plan_parallel_setup(
    plan: list[dict[str, Any]],
    *,
    parallel: int,
    prepare_parallel: bool,
    clean_processors: bool,
) -> None:
    if not prepare_parallel or parallel <= 1:
        return
    for row in plan:
        row_case = Path(str(row["case"]))
        try:
            row["parallel_setup"] = _run().prepare_parallel_case(
                row_case,
                parallel=parallel,
                clean_processors=clean_processors,
                dry_run=True,
            )
        except ValueError as exc:
            row["parallel_setup_error"] = str(exc)


def _run_queue_backend(
    payload: dict[str, Any],
    *,
    plan: list[dict[str, Any]],
    solver: str | None,
    parallel: int,
    mpi: str | None,
    max_parallel: int,
    poll_interval: float,
    backend: str,
    prepare_parallel: bool,
    clean_processors: bool,
) -> None:
    if backend == "process":
        if max_parallel == 1:
            _queue_sequential_process_backend(
                payload,
                plan=plan,
                solver=solver,
                parallel=parallel,
                mpi=mpi,
                prepare_parallel=prepare_parallel,
                clean_processors=clean_processors,
            )
        else:
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


def _queue_payload_init(
    *,
    plan: list[dict[str, Any]],
    normalized_cases: list[Path],
    max_parallel: int,
    parallel: int,
    poll_interval: float,
    dry_run: bool,
    backend: str,
    prepare_parallel: bool,
    clean_processors: bool,
    queue_root: Path | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "queue_id": None,
        "queue_root": None,
        "queue_path": None,
        "count": len(plan),
        "max_parallel": max_parallel,
        "parallel": parallel,
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
    if dry_run:
        return payload
    queue_record = _queue_record_path(normalized_cases, queue_root=queue_root)
    payload["queue_id"] = queue_record.stem
    payload["queue_root"] = str(queue_record.parent.parent.resolve())
    payload["queue_path"] = str(queue_record.resolve())
    payload["created_at"] = time.time()
    payload["updated_at"] = payload["created_at"]
    return payload


def _queue_sequential_process_backend(
    payload: dict[str, Any],
    *,
    plan: list[dict[str, Any]],
    solver: str | None,
    parallel: int,
    mpi: str | None,
    prepare_parallel: bool,
    clean_processors: bool,
) -> None:
    for row in plan:
        case_path = Path(str(row["case"]))
        try:
            name, command = _run().solver_command(
                case_path,
                solver=solver,
                parallel=parallel,
                mpi=mpi,
            )
            if parallel > 1 and "-parallel" in command and prepare_parallel:
                _run().prepare_parallel_case(
                    case_path,
                    parallel=parallel,
                    clean_processors=clean_processors,
                    dry_run=False,
                )
            result = _run().execute_solver_case_command(
                case_path,
                name,
                command,
                parallel=parallel,
                mpi=mpi,
                background=False,
                log_path=Path(f"log.{runner_service.safe_name(name)}"),
            )
        except ValueError as exc:
            payload["failed_to_start"].append({"case": str(case_path), "error": str(exc)})
            payload["ok"] = False
            _queue_write_record(payload)
            continue
        started = {
            "case": str(case_path),
            "pid": None,
            "name": name,
            "log_path": str(result.log_path) if result.log_path is not None else "",
            "started_at": time.time(),
        }
        payload["started"].append(started)
        _queue_write_record(payload)
        status_row = _run().status_row_payload(case_path, lightweight=False)
        finished = _queue_finished_row(
            status_row,
            case=str(case_path),
            pid=None,
            returncode=result.returncode,
        )
        payload["finished"].append(finished)
        _queue_write_record(payload)
        if int(result.returncode) != 0:
            payload["ok"] = False
            _queue_write_record(payload)


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
        _queue_launch_until_full(
            payload,
            pending=pending,
            active=active,
            solver=solver,
            parallel=parallel,
            mpi=mpi,
            prepare_parallel=prepare_parallel,
            clean_processors=clean_processors,
        )
        if not active:
            break
        time.sleep(max(0.05, poll_interval))
        active[:] = _queue_poll_active(payload, active)


def _queue_launch_until_full(
    payload: dict[str, Any],
    *,
    pending: list[dict[str, Any]],
    active: list[dict[str, Any]],
    solver: str | None,
    parallel: int,
    mpi: str | None,
    prepare_parallel: bool,
    clean_processors: bool,
) -> None:
    while pending and len(active) < int(payload["max_parallel"]):
        row = pending.pop(0)
        started = _queue_start_background_row(
            payload,
            row,
            solver=solver,
            parallel=parallel,
            mpi=mpi,
            prepare_parallel=prepare_parallel,
            clean_processors=clean_processors,
        )
        if started:
            active.append(started)


def _queue_start_background_row(
    payload: dict[str, Any],
    row: dict[str, Any],
    *,
    solver: str | None,
    parallel: int,
    mpi: str | None,
    prepare_parallel: bool,
    clean_processors: bool,
) -> dict[str, Any] | None:
    case_path = Path(str(row["case"]))
    name, command = _run().solver_command(case_path, solver=solver, parallel=parallel, mpi=mpi)
    try:
        _prepare_queue_parallel_case(
            case_path,
            command,
            parallel=parallel,
            prepare_parallel=prepare_parallel,
            clean_processors=clean_processors,
        )
        result = _run().execute_case_command(
            case_path,
            name,
            command,
            background=True,
            detached=True,
        )
    except ValueError as exc:
        _queue_failed_to_start(payload, case_path, str(exc))
        return None
    if result.pid is None:
        _queue_failed_to_start(payload, case_path, "missing background pid")
        return None
    started = {
        "case": str(case_path),
        "pid": int(result.pid),
        "name": name,
        "log_path": str(result.log_path) if result.log_path is not None else "",
        "started_at": time.time(),
    }
    payload["started"].append(started)
    _queue_write_record(payload)
    return started


def _prepare_queue_parallel_case(
    case_path: Path,
    command: list[str],
    *,
    parallel: int,
    prepare_parallel: bool,
    clean_processors: bool,
) -> None:
    if parallel <= 1 or "-parallel" not in command or not prepare_parallel:
        return
    _run().prepare_parallel_case(
        case_path,
        parallel=parallel,
        clean_processors=clean_processors,
        dry_run=False,
    )


def _queue_failed_to_start(payload: dict[str, Any], case_path: Path, error: str) -> None:
    payload["failed_to_start"].append({"case": str(case_path), "error": error})
    payload["ok"] = False
    _queue_write_record(payload)


def _queue_poll_active(
    payload: dict[str, Any],
    active: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    still_active: list[dict[str, Any]] = []
    for row in active:
        pid = int(row["pid"])
        if _pid_running(pid):
            still_active.append(row)
            continue
        status_row = _run().status_row_payload(Path(str(row["case"])))
        payload["finished"].append(
            _queue_finished_row(status_row, case=str(row["case"]), pid=pid, returncode=None),
        )
        _queue_write_record(payload)
    return still_active


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
            _queue_write_record(payload)
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
            _queue_write_record(payload)
            continue
        if prepare_parallel and parallel > 1:
            try:
                _run().prepare_parallel_case(
                    case_path,
                    parallel=parallel,
                    clean_processors=clean_processors,
                    dry_run=False,
                )
            except ValueError as exc:
                payload["failed_to_start"].append({"case": str(case_path), "error": str(exc)})
                payload["ok"] = False
                _queue_write_record(payload)
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
        _queue_write_record(payload)
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
        status_row = _run().status_row_payload(case_path)
        row = _queue_finished_row(status_row, case=str(case_path), pid=None, returncode=None)
        payload["finished"].append(row)
        if str(case_path.resolve()) in failed_map:
            payload["ok"] = False
        _queue_write_record(payload)


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
                "outcome": "unknown",
                "returncode": None,
                "stop_reason": "not finished",
                "end_time": None,
                "latest_time": None,
                "eta_seconds": None,
            },
        )
        _queue_write_record(payload)


def _queue_record_path(cases: list[Path], *, queue_root: Path | None) -> Path:
    if queue_root is not None:
        root = queue_root.expanduser().resolve()
    else:
        root = _queue_common_root(cases)
    queue_id = f"queue-{int(time.time())}"
    return root / ".ofti" / "queues" / f"{queue_id}.json"


def _queue_common_root(cases: list[Path]) -> Path:
    parents = [str(path.expanduser().resolve().parent) for path in cases]
    if not parents:
        return Path.cwd().resolve()
    with suppress(ValueError):
        common = Path(os.path.commonpath(parents)).resolve()
        if str(common) != os.path.sep:
            return common
    return Path(parents[0]).resolve()


def _queue_write_record(payload: dict[str, Any]) -> None:
    queue_path_raw = payload.get("queue_path")
    if not isinstance(queue_path_raw, str) or not queue_path_raw.strip():
        return
    queue_path = Path(queue_path_raw)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = time.time()
    queue_path.write_text(
        json.dumps(_queue_record_payload(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _queue_mark_complete(payload: dict[str, Any]) -> None:
    payload["completed_at"] = time.time()
    payload["summary"] = _queue_summary(payload)
    _queue_write_record(payload)


def _queue_record_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    started = list(payload.get("started", []))
    finished = list(payload.get("finished", []))
    failed = list(payload.get("failed_to_start", []))
    return {
        "format": QUEUE_FORMAT,
        "format_version": QUEUE_FORMAT_VERSION,
        "queue_id": payload.get("queue_id"),
        "queue_root": payload.get("queue_root"),
        "queue_path": payload.get("queue_path"),
        "created_at": _queue_timestamp(payload.get("created_at")),
        "updated_at": _queue_timestamp(payload.get("updated_at")),
        "completed_at": _queue_timestamp(payload.get("completed_at")),
        "dry_run": bool(payload.get("dry_run")),
        "backend": payload.get("backend"),
        "count": int(payload.get("count", 0) or 0),
        "max_parallel": int(payload.get("max_parallel", 1) or 1),
        "parallel": int(payload.get("parallel", 0) or 0),
        "ok": bool(payload.get("ok", False)),
        "summary": _queue_summary(payload),
        "planned": list(payload.get("planned", [])),
        "started": started,
        "finished": finished,
        "failed_to_start": failed,
    }


def _queue_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    started = list(payload.get("started", []))
    finished = list(payload.get("finished", []))
    failed = list(payload.get("failed_to_start", []))
    return {
        "planned": int(payload.get("count", 0) or 0),
        "started": len(started),
        "finished": len(finished),
        "failed_to_start": len(failed),
        "running": max(0, len(started) - len(finished)),
        "outcomes": _queue_outcome_counts(finished),
    }


def _queue_outcome_counts(rows: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        data = cast("dict[str, object]", row)
        outcome = str(data.get("outcome") or "unknown")
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def _queue_timestamp(value: object) -> str | None:
    if isinstance(value, int | float):
        timestamp = datetime.fromtimestamp(float(value), UTC).replace(microsecond=0)
        return timestamp.isoformat().replace("+00:00", "Z")
    if isinstance(value, str) and value:
        return value
    return None


def _queue_finished_row(
    status_row: Mapping[str, Any],
    *,
    case: str,
    pid: int | None,
    returncode: int | None,
) -> dict[str, Any]:
    outcome = _queue_outcome(status_row, returncode=returncode)
    state = "crashed" if outcome == "crashed" else status_row["state"]
    stop_reason = str(status_row.get("stop_reason") or "")
    if outcome == "crashed":
        stop_reason = "crashed"
    elif outcome == "criteria":
        stop_reason = "criteria_met"
    elif outcome == "time":
        stop_reason = "end_time_reached"
    return {
        "case": case,
        "pid": pid,
        "returncode": returncode,
        "state": state,
        "outcome": outcome,
        "stop_reason": stop_reason,
        "latest_time": status_row["latest_time"],
        "end_time": status_row.get("end_time"),
        "eta_seconds": status_row["eta_seconds"],
    }


def _queue_outcome(status_row: Mapping[str, Any], *, returncode: int | None) -> str:
    if returncode is not None and returncode != 0:
        return "crashed"
    latest_time = status_row.get("latest_time")
    end_time = status_row.get("end_time")
    if (
        isinstance(latest_time, (int, float))
        and isinstance(end_time, (int, float))
        and latest_time >= end_time
    ):
        return "time"
    if (
        int(status_row.get("criteria_total", 0) or 0) > 0
        and int(status_row.get("criteria_failed", 0) or 0) == 0
        and int(status_row.get("criteria_unknown", 0) or 0) == 0
        and int(status_row.get("criteria_passed", 0) or 0) > 0
    ):
        return "criteria"
    state = str(status_row.get("state") or "")
    if state in {"error", "failed"}:
        return "crashed" if returncode is None else "failed"
    if returncode == 0:
        return "completed"
    return "stopped"


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
