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
    jobs: list[dict[str, Any]]
    jobs_total: int
    jobs_running: int
    jobs_tracked_running: int
    untracked_processes: list[SolverProcessRow]


class CaseStatusPayload(TypedDict):
    case: str
    solver: str | None
    solver_error: str | None
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
    jobs: list[dict[str, Any]]
    tracked_solver_processes: list[SolverProcessRow]
    untracked_solver_processes: list[SolverProcessRow]


def current_payload(
    case_path: Path,
    *,
    resolve_solver_name_fn: Callable[[Path], tuple[str | None, str | None]],
    refresh_jobs_fn: Callable[[Path], list[dict[str, Any]]],
    running_job_pids_fn: Callable[[list[dict[str, Any]]], list[int]],
    scan_proc_solver_processes_fn: Callable[..., list[SolverProcessRow]],
) -> CurrentPayload:
    solver, solver_error = resolve_solver_name_fn(case_path)
    jobs = refresh_jobs_fn(case_path)
    active_jobs = [job for job in jobs if job.get("status") in {"running", "paused"}]
    tracked_pids = set(running_job_pids_fn(active_jobs))
    untracked: list[SolverProcessRow] = []
    if solver and solver_error is None:
        untracked = scan_proc_solver_processes_fn(
            case_path,
            solver,
            tracked_pids=tracked_pids,
        )
    elif solver_error is not None:
        untracked = scan_proc_solver_processes_fn(
            case_path,
            None,
            tracked_pids=tracked_pids,
        )
        if not untracked:
            untracked = scan_proc_solver_processes_fn(
                case_path,
                None,
                tracked_pids=tracked_pids,
                require_case_target=False,
            )
    running_count = len(active_jobs) if active_jobs else len(untracked)
    return {
        "case": str(case_path),
        "solver": solver,
        "solver_error": solver_error,
        "jobs": active_jobs,
        "jobs_total": len(jobs),
        "jobs_running": running_count,
        "jobs_tracked_running": len(active_jobs),
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
    running_heuristic = has_live_pids or bool(runtime["log_fresh"])
    running_count = len(active_jobs) if active_jobs else len(untracked_live)
    return {
        "case": str(case_path),
        "solver": solver,
        "solver_error": solver_error,
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
        "jobs": jobs,
        "tracked_solver_processes": tracked_live,
        "untracked_solver_processes": untracked_live,
    }


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
