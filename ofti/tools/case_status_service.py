from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, TypedDict

from ofti.tools import process_scan_service

SolverProcessRow: TypeAlias = process_scan_service.ProcRow


class CurrentPayload(TypedDict):
    case: str
    solver: str | None
    solver_error: str | None
    proc_access_warning: str | None
    jobs: list[dict[str, Any]]
    jobs_total: int
    jobs_running: int
    jobs_tracked_running: int
    jobs_registry_running: int
    runs: list[dict[str, Any]]
    process_visibility: dict[str, Any] | None
    untracked_processes: list[SolverProcessRow]


class CaseStatusPayload(TypedDict):
    case: str
    solver: str | None
    solver_error: str | None
    proc_access_warning: str | None
    solver_status: str | None
    latest_time: float | str | None
    latest_iteration: int | None
    latest_delta_t: float | None
    sec_per_iter: float | None
    run_time_control: dict[str, Any]
    eta_seconds_to_criteria_start: float | None
    eta_seconds_to_end_time: float | None
    log_path: str | None
    log_fresh: bool
    running: bool
    jobs_total: int
    jobs_running: int
    jobs_tracked_running: int
    jobs_registry_running: int
    jobs: list[dict[str, Any]]
    runs: list[dict[str, Any]]
    process_visibility: dict[str, Any] | None
    tracked_solver_processes: list[SolverProcessRow]
    untracked_solver_processes: list[SolverProcessRow]


def current_payload(
    case_path: Path,
    *,
    resolve_solver_name_fn: Callable[[Path], tuple[str | None, str | None]],
    refresh_jobs_fn: Callable[[Path], list[dict[str, Any]]],
    running_job_pids_fn: Callable[[list[dict[str, Any]]], list[int]],
    scan_proc_solver_processes_fn: Callable[..., list[SolverProcessRow]],
    live: bool = False,
) -> CurrentPayload:
    solver, solver_error = resolve_solver_name_fn(case_path)
    jobs = refresh_jobs_fn(case_path)
    active_jobs = [job for job in jobs if job.get("status") in {"running", "paused"}]
    tracked_pids = set(running_job_pids_fn(active_jobs))
    solver_query = solver if solver and solver_error is None else None
    untracked = scan_proc_solver_processes_fn(
        case_path,
        solver_query,
        tracked_pids=tracked_pids,
        require_case_target=not live,
    )
    untracked_count = untracked_running_count(untracked)
    running_count = len(active_jobs) + untracked_count
    runs = canonical_run_rows(case_path, active_jobs, untracked)
    return {
        "case": str(case_path),
        "solver": solver,
        "solver_error": solver_error,
        "proc_access_warning": None,
        "jobs": active_jobs,
        "jobs_total": len(jobs),
        "jobs_running": running_count,
        "jobs_tracked_running": len(active_jobs),
        "jobs_registry_running": len(active_jobs),
        "runs": runs,
        "process_visibility": None,
        "untracked_processes": untracked,
    }


def status_payload(
    case_path: Path,
    *,
    resolve_solver_name_fn: Callable[[Path], tuple[str | None, str | None]],
    refresh_jobs_fn: Callable[[Path], list[dict[str, Any]]],
    running_job_pids_fn: Callable[[list[dict[str, Any]]], list[int]],
    scan_proc_solver_processes_fn: Callable[..., list[SolverProcessRow]],
    runtime_control_snapshot_fn: Callable[..., Any],
    latest_solver_job_fn: Callable[[Path, str], Any],
    solver_status_text_fn: Callable[[Any], str],
    latest_time_fn: Callable[[Path], float | str | None],
    lightweight: bool = False,
    tail_bytes: int | None = None,
) -> CaseStatusPayload:
    solver, solver_error = resolve_solver_name_fn(case_path)
    jobs = refresh_jobs_fn(case_path)
    active_jobs = [job for job in jobs if job.get("status") in {"running", "paused"}]
    tracked_pids = set(running_job_pids_fn(active_jobs))
    live_processes: list[SolverProcessRow] = []
    if solver and solver_error is None:
        live_processes = scan_proc_solver_processes_fn(
            case_path,
            solver,
            tracked_pids=tracked_pids,
            include_tracked=True,
        )
    elif solver_error is not None:
        live_processes = scan_proc_solver_processes_fn(
            case_path,
            None,
            tracked_pids=tracked_pids,
            include_tracked=True,
        )
    tracked_live = [row for row in live_processes if bool(row.get("tracked"))]
    untracked_live = [row for row in live_processes if not bool(row.get("tracked"))]

    solver_status: str | None = None
    if solver:
        summary = latest_solver_job_fn(case_path, solver)
        solver_status = solver_status_text_fn(summary) if summary else None

    runtime = _runtime_snapshot(
        runtime_control_snapshot_fn,
        case_path,
        solver,
        lightweight=lightweight,
        tail_bytes=tail_bytes,
    )
    latest_time_value = runtime["latest_time"]
    has_live_pids = bool(live_processes)
    running_heuristic = has_live_pids or (solver is not None and bool(runtime["log_fresh"]))
    untracked_count = untracked_running_count(untracked_live)
    running_count = len(active_jobs) + untracked_count
    runs = canonical_run_rows(case_path, active_jobs, untracked_live)
    return {
        "case": str(case_path),
        "solver": solver,
        "solver_error": solver_error,
        "proc_access_warning": None,
        "solver_status": solver_status,
        "latest_time": (
            latest_time_value if latest_time_value is not None else latest_time_fn(case_path)
        ),
        "latest_iteration": runtime["latest_iteration"],
        "latest_delta_t": runtime["latest_delta_t"],
        "sec_per_iter": runtime["sec_per_iter"],
        "run_time_control": runtime["run_time_control"],
        "eta_seconds_to_criteria_start": runtime["eta_to_criteria_start"],
        "eta_seconds_to_end_time": runtime["eta_to_end_time"],
        "log_path": runtime["log_path"],
        "log_fresh": bool(runtime["log_fresh"]),
        "running": running_heuristic,
        "jobs_total": len(jobs),
        "jobs_running": running_count,
        "jobs_tracked_running": len(active_jobs),
        "jobs_registry_running": len(active_jobs),
        "jobs": jobs,
        "runs": runs,
        "process_visibility": None,
        "tracked_solver_processes": tracked_live,
        "untracked_solver_processes": untracked_live,
    }


def attach_process_visibility(
    payload: dict[str, Any],
    warning: str | None,
) -> None:
    if warning is None:
        return
    payload["proc_access_warning"] = warning
    registry_running = int(payload.get("jobs_registry_running") or 0)
    live_rows = list(payload.get("untracked_processes", [])) + list(
        payload.get("tracked_solver_processes", []),
    )
    payload["process_visibility"] = {
        "limited": True,
        "warning": warning,
        "registry_running": registry_running,
        "live_process_rows": len(live_rows),
        "message": (
            f"process visibility limited: registry shows {registry_running} tracked run(s), "
            "live process scan may be incomplete"
        ),
    }


def canonical_run_rows(
    case_path: Path,
    active_jobs: list[dict[str, Any]],
    untracked_rows: list[SolverProcessRow],
) -> list[dict[str, Any]]:
    runs = [_tracked_run_row(case_path, job) for job in active_jobs]
    tracked_pids = {
        pid
        for run in runs
        for pid in _int_list(run.get("process_group_pids"))
    }
    launcher_pids = {
        int(row["pid"])
        for row in untracked_rows
        if str(row.get("role")) == "launcher" and int(row.get("pid", 0)) > 0
    }
    for row in untracked_rows:
        pid = int(row.get("pid", 0) or 0)
        if pid <= 0 or pid in tracked_pids:
            continue
        role = str(row.get("role") or "solver")
        launcher_pid = row.get("launcher_pid")
        if (
            role == "solver"
            and isinstance(launcher_pid, int)
            and launcher_pid in launcher_pids | tracked_pids
        ):
            continue
        runs.append(_untracked_run_row(row))
    runs.sort(key=lambda item: (str(item.get("case_dir") or ""), int(item.get("pid") or 0)))
    return runs


def _tracked_run_row(case_path: Path, job: dict[str, Any]) -> dict[str, Any]:
    solver_pids = _int_list(job.get("solver_pids"))
    launcher_pid = _int_or_none(job.get("launcher_pid")) or _int_or_none(job.get("pid"))
    pids = _unique_ints([launcher_pid, *solver_pids])
    return {
        "id": job.get("id"),
        "source": "registry",
        "tracked": True,
        "kind": job.get("kind", "solver"),
        "name": job.get("name", "solver"),
        "case_dir": str(job.get("case_dir") or case_path),
        "pid": _int_or_none(job.get("pid")) or launcher_pid,
        "launcher_pid": launcher_pid,
        "solver_pids": solver_pids,
        "process_group_pids": pids,
        "status": job.get("status", "unknown"),
        "log_path": job.get("log") or job.get("log_path"),
        "command": job.get("command", ""),
    }


def _untracked_run_row(row: SolverProcessRow) -> dict[str, Any]:
    pid = int(row.get("pid", 0) or 0)
    solver_pids = _int_list(row.get("solver_pids"))
    launcher_pid = row.get("launcher_pid") if isinstance(row.get("launcher_pid"), int) else None
    if str(row.get("role")) == "launcher":
        launcher_pid = pid
    pids = _unique_ints([launcher_pid, pid, *solver_pids])
    return {
        "id": None,
        "source": "procfs",
        "tracked": False,
        "kind": "solver",
        "name": row.get("solver") or "solver",
        "case_dir": row.get("case", ""),
        "pid": pid,
        "launcher_pid": launcher_pid,
        "solver_pids": solver_pids,
        "process_group_pids": pids,
        "status": "running",
        "role": row.get("role"),
        "log_path": None,
        "command": row.get("command", ""),
    }


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and item > 0]


def _unique_ints(values: list[int | None]) -> list[int]:
    result: list[int] = []
    for value in values:
        if isinstance(value, int) and value > 0 and value not in result:
            result.append(value)
    return result


def _runtime_snapshot(
    runtime_control_snapshot_fn: Callable[..., Any],
    case_path: Path,
    solver: str | None,
    *,
    lightweight: bool,
    tail_bytes: int | None,
) -> Any:
    try:
        return runtime_control_snapshot_fn(
            case_path,
            solver,
            lightweight=lightweight,
            max_log_bytes=tail_bytes,
        )
    except TypeError:
        return runtime_control_snapshot_fn(case_path, solver)


def untracked_running_count(rows: list[SolverProcessRow]) -> int:
    if not rows:
        return 0
    launcher_pids = {
        pid
        for row in rows
        if str(row.get("role")) == "launcher" and (pid := _int_or_none(row.get("pid")))
    }
    solver_pids = {
        pid
        for row in rows
        if str(row.get("role")) == "solver"
        and (pid := _int_or_none(row.get("pid")))
        and not _owned_by_launcher(row, launcher_pids)
    }
    return len(launcher_pids) + len(solver_pids)


def _owned_by_launcher(row: SolverProcessRow, launcher_pids: set[int]) -> bool:
    launcher_pid = _int_or_none(row.get("launcher_pid"))
    return launcher_pid in launcher_pids if launcher_pid is not None else False
