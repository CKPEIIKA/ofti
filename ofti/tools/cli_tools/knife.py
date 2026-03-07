from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from ofti.core.dict_compare import compare_case_dicts
from ofti.core.entry_io import write_entry
from ofti.core.solver_checks import resolve_solver_name
from ofti.core.solver_status import latest_solver_job, solver_status_text
from ofti.core.times import latest_time
from ofti.tools.case_doctor import build_case_doctor_report
from ofti.tools.job_registry import refresh_jobs

from .common import require_case_dir


def doctor_payload(case_dir: Path) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    report = build_case_doctor_report(case_path)
    return {
        "case": str(case_path),
        "lines": report["lines"],
        "errors": report["errors"],
        "warnings": report["warnings"],
    }


def doctor_exit_code(payload: dict[str, Any]) -> int:
    errors = payload.get("errors", [])
    return 1 if errors else 0


def current_payload(case_dir: Path) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    solver, solver_error = resolve_solver_name(case_path)
    jobs = refresh_jobs(case_path)
    running_jobs = [job for job in jobs if job.get("status") == "running"]
    tracked_pids = set(_running_job_pids(running_jobs))
    untracked: list[dict[str, Any]] = []
    if solver and solver_error is None:
        untracked = _scan_proc_solver_processes(
            case_path,
            solver,
            tracked_pids=tracked_pids,
        )
    return {
        "case": str(case_path),
        "solver": solver,
        "solver_error": solver_error,
        "jobs": running_jobs,
        "jobs_total": len(jobs),
        "jobs_running": len(running_jobs),
        "untracked_processes": untracked,
    }


def compare_payload(left_case: Path, right_case: Path) -> dict[str, Any]:
    left = require_case_dir(left_case)
    right = require_case_dir(right_case)
    diffs = compare_case_dicts(left, right)
    return {
        "left_case": str(left),
        "right_case": str(right),
        "diff_count": len(diffs),
        "diffs": [
            {
                "rel_path": diff.rel_path,
                "missing_in_left": diff.missing_in_left,
                "missing_in_right": diff.missing_in_right,
                "error": diff.error,
            }
            for diff in diffs
        ],
    }


def status_payload(case_dir: Path) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    solver, solver_error = resolve_solver_name(case_path)
    jobs = refresh_jobs(case_path)
    running_jobs = [job for job in jobs if job.get("status") == "running"]
    solver_status: str | None = None
    if solver:
        summary = latest_solver_job(case_path, solver)
        solver_status = solver_status_text(summary) if summary else None
    return {
        "case": str(case_path),
        "solver": solver,
        "solver_error": solver_error,
        "solver_status": solver_status,
        "latest_time": latest_time(case_path),
        "jobs_total": len(jobs),
        "jobs_running": len(running_jobs),
        "jobs": jobs,
    }


def preflight_payload(case_dir: Path) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    control_dict_path = case_path / "system" / "controlDict"
    control_dict_ok = control_dict_path.is_file()
    solver, solver_error = resolve_solver_name(case_path)
    if solver is None and control_dict_ok:
        fallback_solver = _fallback_solver(control_dict_path)
        if fallback_solver:
            solver = fallback_solver
            solver_error = None
    checks = {
        "case_dir": True,
        "system/controlDict": control_dict_ok,
        "solver_entry": solver_error is None and bool(solver),
        "0_or_0.orig": (case_path / "0").is_dir() or (case_path / "0.orig").is_dir(),
        "constant/polyMesh/boundary": (case_path / "constant" / "polyMesh" / "boundary").is_file(),
        "openfoam_env": bool(os.environ.get("WM_PROJECT_DIR") or shutil.which("foamVersion")),
    }
    required_checks = ("system/controlDict", "solver_entry")
    ok = all(checks[name] for name in required_checks)
    return {
        "case": str(case_path),
        "ok": ok,
        "checks": checks,
        "solver": solver,
        "solver_error": solver_error,
    }


def _fallback_solver(control_dict_path: Path) -> str | None:
    try:
        text = control_dict_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line or not line.startswith("application"):
            continue
        parts = line.replace(";", " ").split()
        if len(parts) >= 2:
            return parts[1]
    return None


def set_entry_payload(case_dir: Path, rel_file: str, key: str, value: str) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    file_path = (case_path / rel_file).resolve()
    if not file_path.is_file():
        raise ValueError(f"dictionary not found: {file_path}")
    ok = write_entry(file_path, key, value)
    return {
        "case": str(case_path),
        "file": str(file_path),
        "key": key,
        "value": value,
        "ok": bool(ok),
    }


def _running_job_pids(jobs: list[dict[str, Any]]) -> list[int]:
    pids: list[int] = []
    for job in jobs:
        pid = job.get("pid")
        if isinstance(pid, int) and pid > 0:
            pids.append(pid)
    return pids


def _scan_proc_solver_processes(
    case_path: Path,
    solver: str,
    *,
    tracked_pids: set[int],
    proc_root: Path = Path("/proc"),
) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return processes
    for entry in entries:
        if not entry.is_dir():
            continue
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in tracked_pids:
            continue
        args = _read_proc_args(entry)
        if not args or not _args_match_solver(args, solver):
            continue
        if not _targets_case(entry, args, case_path):
            continue
        processes.append(
            {
                "pid": pid,
                "solver": solver,
                "command": " ".join(args),
            },
        )
    processes.sort(key=lambda item: int(item.get("pid", 0)))
    return processes


def _read_proc_args(proc_dir: Path) -> list[str]:
    cmdline_path = proc_dir / "cmdline"
    try:
        raw = cmdline_path.read_bytes()
    except OSError:
        return []
    if not raw:
        return []
    return [part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part]


def _args_match_solver(args: list[str], solver: str) -> bool:
    solver_name = solver.lower()
    for arg in args:
        if Path(arg).name.lower() == solver_name:
            return True
        cleaned = arg.replace(";", " ").replace("&&", " ")
        for token in cleaned.split():
            if Path(token).name.lower() == solver_name:
                return True
    return False


def _targets_case(proc_dir: Path, args: list[str], case_path: Path) -> bool:
    resolved_case = case_path.resolve()
    cwd_path = _proc_cwd(proc_dir)
    if cwd_path == resolved_case:
        return True
    for idx, arg_value in enumerate(args):
        if arg_value != "-case":
            continue
        if idx + 1 >= len(args):
            continue
        candidate = Path(args[idx + 1]).expanduser()
        if candidate == resolved_case:
            return True
        if not candidate.is_absolute():
            base = cwd_path if cwd_path is not None else resolved_case
            if (base / candidate).resolve() == resolved_case:
                return True
    return False


def _proc_cwd(proc_dir: Path) -> Path | None:
    cwd_link = proc_dir / "cwd"
    try:
        return cwd_link.resolve()
    except OSError:
        return None
