"""Untracked solver stopping helpers for the knife service facade."""

from __future__ import annotations

import os
import signal
from pathlib import Path
from typing import Any, cast

from ofti.tools import process_scan_service
from ofti.tools.job_registry import refresh_jobs
from ofti.tools.knife_process import _running_job_pids


def stop_untracked_solver_processes(case_path: Path, *, signal_name: str) -> dict[str, Any]:
    if not process_scan_service.is_case_dir(case_path):
        return _untracked_stop_empty(case_path, reason="case_dir_is_not_openfoam_case")
    case_str = str(case_path.resolve())
    selected_rows = _untracked_solver_rows(case_path, case_str=case_str)
    if not selected_rows:
        return _untracked_stop_empty(case_path.resolve(), reason="no_untracked_solver_processes")
    plan = _untracked_stop_plan(selected_rows)
    stopped, failed = _signal_untracked_rows(
        selected_rows,
        plan=plan,
        case_str=case_str,
        signal_code=_signal_number(signal_name),
    )
    return {
        "case": case_str,
        "selected": len(stopped) + len(failed),
        "stopped": stopped,
        "failed": failed,
        "launcher_pids": plan["launchers"],
        "solver_pids": plan["solver_pids"],
    }


def _untracked_stop_empty(case_path: Path, *, reason: str) -> dict[str, Any]:
    return {
        "case": str(case_path),
        "selected": 0,
        "stopped": [],
        "failed": [],
        "reason": reason,
    }


def _untracked_solver_rows(case_path: Path, *, case_str: str) -> list[dict[str, Any]]:
    active_jobs = [
        job
        for job in refresh_jobs(case_path)
        if job.get("status") in {"running", "paused"}
    ]
    rows = process_scan_service.scan_proc_solver_processes(
        case_path,
        None,
        tracked_pids=set(_running_job_pids(active_jobs)),
        include_tracked=False,
        require_case_target=True,
    )
    return [cast("dict[str, Any]", row) for row in rows if str(row.get("case") or "") == case_str]


def _untracked_stop_plan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    launchers = _launcher_pids(rows)
    solver_rows = [row for row in rows if _is_positive_role_pid(row, "solver")]
    solver_pids = sorted({int(row["pid"]) for row in solver_rows})
    launcher_groups = {pid: _process_group_if_leader(pid) for pid in launchers}
    safe_launchers = {pid for pid, pgid in launcher_groups.items() if pgid == pid}
    if safe_launchers:
        solver_pids = _solver_pids_without_launcher_groups(solver_rows, solver_pids, safe_launchers)
    return {
        "launchers": sorted(launchers),
        "solver_pids": solver_pids,
        "launcher_groups": launcher_groups,
    }


def _launcher_pids(rows: list[dict[str, Any]]) -> set[int]:
    return {
        int(row["pid"])
        for row in rows
        if str(row.get("role")) == "launcher" and int(row.get("pid", 0)) > 0
    }


def _is_positive_role_pid(row: dict[str, Any], role: str) -> bool:
    return str(row.get("role")) == role and int(row.get("pid", 0)) > 0


def _solver_pids_without_launcher_groups(
    solver_rows: list[dict[str, Any]],
    solver_pids: list[int],
    safe_launchers: set[int],
) -> list[int]:
    solver_launcher = {
        int(row["pid"]): _to_positive_int(row.get("launcher_pid"))
        for row in solver_rows
    }
    return [pid for pid in solver_pids if solver_launcher.get(pid) not in safe_launchers]


def _to_positive_int(value: Any) -> int | None:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _signal_untracked_rows(
    rows: list[dict[str, Any]],
    *,
    plan: dict[str, Any],
    case_str: str,
    signal_code: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stopped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    stop_pids = set(plan["launchers"]) | set(plan["solver_pids"])
    for row in rows:
        pid = int(row.get("pid", 0) or 0)
        if pid not in stop_pids:
            continue
        stopped_row, failed_row = _signal_untracked_row(
            row,
            plan=plan,
            case_str=case_str,
            signal_code=signal_code,
        )
        if stopped_row is not None:
            stopped.append(stopped_row)
        if failed_row is not None:
            failed.append(failed_row)
    return stopped, failed


def _signal_untracked_row(
    row: dict[str, Any],
    *,
    plan: dict[str, Any],
    case_str: str,
    signal_code: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    pid = int(row.get("pid", 0) or 0)
    role = str(row.get("role") or "solver")
    try:
        method, pgid = _send_untracked_signal(pid, role, plan, signal_code=signal_code)
    except OSError as exc:
        return None, _untracked_signal_failed_row(pid, role, case_str=case_str, error=str(exc))
    return _untracked_stopped_row(row, pid, role, case_str=case_str, method=method, pgid=pgid), None


def _send_untracked_signal(
    pid: int,
    role: str,
    plan: dict[str, Any],
    *,
    signal_code: int,
) -> tuple[str, int | None]:
    launcher_groups = plan["launcher_groups"]
    if role == "launcher" and launcher_groups.get(pid) == pid:
        os.killpg(pid, signal_code)
        return "process_group", pid
    os.kill(pid, signal_code)
    return "process", None


def _untracked_signal_failed_row(
    pid: int,
    role: str,
    *,
    case_str: str,
    error: str,
) -> dict[str, Any]:
    return {
        "id": None,
        "pid": pid,
        "name": f"untracked-{role}",
        "kind": "untracked",
        "role": role,
        "case": case_str,
        "error": error,
    }


def _untracked_stopped_row(
    row: dict[str, Any],
    pid: int,
    role: str,
    *,
    case_str: str,
    method: str,
    pgid: int | None,
) -> dict[str, Any]:
    stopped = {
        "id": None,
        "pid": pid,
        "name": f"untracked-{role}",
        "kind": "untracked",
        "role": role,
        "case": case_str,
        "launcher_pid": row.get("launcher_pid"),
        "solver_pids": row.get("solver_pids", []),
        "command": row.get("command"),
        "method": method,
    }
    if pgid is not None:
        stopped["pgid"] = pgid
    return stopped


def _process_group_if_leader(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def _signal_number(name: str) -> int:
    attr = f"SIG{name.strip().upper()}"
    value = getattr(signal, attr, None)
    if isinstance(value, int):
        return value
    return signal.SIGTERM
