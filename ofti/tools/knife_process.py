"""Backward-compatible aliases for solver-process scanning helpers.

Thin wrappers delegating to ``process_scan_service``. Kept so the ``ofti knife``
command facade and its tests can reach the underscore-prefixed names without
the knife service module carrying the pass-through definitions.
"""

from __future__ import annotations

from pathlib import Path

from ofti.tools import process_scan_service
from ofti.tools.process_scan_service import ProcEntry


def _running_job_pids(jobs: list[dict[str, object]]) -> list[int]:
    return process_scan_service.running_job_pids(jobs)


def _scan_proc_solver_processes(
    case_path: Path,
    solver: str | None,
    *,
    tracked_pids: set[int],
    proc_root: Path = Path("/proc"),
    include_tracked: bool = False,
    require_case_target: bool = True,
) -> list[process_scan_service.ProcRow]:
    return process_scan_service.scan_proc_solver_processes(
        case_path,
        solver,
        tracked_pids=tracked_pids,
        proc_root=proc_root,
        include_tracked=include_tracked,
        require_case_target=require_case_target,
    )


def _proc_table(proc_root: Path) -> dict[int, ProcEntry]:
    return process_scan_service.proc_table(proc_root)


def _launcher_pids_for_case(
    table: dict[int, ProcEntry],
    solver: str | None,
    case_path: Path,
) -> set[int]:
    return process_scan_service.launcher_pids_for_case(table, solver, case_path)


def _launcher_has_solver_descendant(
    pid: int,
    table: dict[int, ProcEntry],
    solver: str | None,
) -> bool:
    return process_scan_service.launcher_has_solver_descendant(pid, table, solver)


def _has_ancestor(pid: int, ancestors: set[int], table: dict[int, ProcEntry]) -> bool:
    return process_scan_service.has_ancestor(pid, ancestors, table)


def _read_proc_args(proc_dir: Path) -> list[str]:
    return process_scan_service.read_proc_args(proc_dir)


def _read_proc_ppid(proc_dir: Path) -> int:
    return process_scan_service.read_proc_ppid(proc_dir)


def _process_role(args: list[str], solver: str | None) -> str | None:
    return process_scan_service.process_role(args, solver)


def _args_match_solver(args: list[str], solver: str) -> bool:
    return process_scan_service.args_match_solver(args, solver)


def _token_matches_solver(text: str, solver: str) -> bool:
    return process_scan_service.token_matches_solver(text, solver)


def _targets_case(proc_dir: Path, args: list[str], case_path: Path) -> bool:
    return process_scan_service.targets_case(proc_dir, args, case_path)


def _entry_targets_case(entry: ProcEntry, case_path: Path) -> bool:
    return process_scan_service.entry_targets_case(entry, case_path)


def _proc_cwd(proc_dir: Path) -> Path | None:
    return process_scan_service.proc_cwd(proc_dir)


def _launcher_descendant_targets_case(
    pid: int,
    table: dict[int, ProcEntry],
    case_path: Path,
) -> bool:
    return process_scan_service.launcher_descendant_targets_case(pid, table, case_path)


def _path_within(path: Path, root: Path) -> bool:
    return process_scan_service.path_within(path, root)


def _looks_like_solver_args(args: list[str]) -> bool:
    return process_scan_service.looks_like_solver_args(args)


def _guess_solver_from_args(args: list[str]) -> str:
    return process_scan_service.guess_solver_from_args(args)
