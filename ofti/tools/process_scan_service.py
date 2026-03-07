from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

_MPI_LAUNCHERS = {"mpirun", "mpiexec", "mpiexec.hydra", "orterun", "srun"}


@dataclass(frozen=True)
class ProcEntry:
    pid: int
    ppid: int
    args: list[str]
    cwd: Path | None


class ProcRow(TypedDict, total=False):
    pid: int
    ppid: int
    solver: str | None
    role: str
    tracked: bool
    case: str | None
    command: str


def running_job_pids(jobs: list[dict[str, Any]]) -> list[int]:
    pids: list[int] = []
    for job in jobs:
        pid = job.get("pid")
        if isinstance(pid, int) and pid > 0:
            pids.append(pid)
    return pids


def scan_proc_solver_processes(
    case_path: Path,
    solver: str | None,
    *,
    tracked_pids: set[int],
    proc_root: Path = Path("/proc"),
    include_tracked: bool = False,
    require_case_target: bool = True,
) -> list[ProcRow]:
    table = proc_table(proc_root)
    case_root = case_path.resolve()
    case_root_is_case = is_case_dir(case_root)
    solver_name = solver.lower() if solver else None
    launcher_pids = launcher_pids_for_case(table, solver_name, case_root)
    processes: list[ProcRow] = []
    for entry in table.values():
        if entry.pid in tracked_pids and not include_tracked:
            continue
        if not entry.args:
            continue
        role = process_role(entry.args, solver_name)
        if role is None:
            continue
        inferred_case = infer_case_path(entry, table)
        inferred_in_scope = inferred_case is not None and (
            
                inferred_case == case_root
                if case_root_is_case
                else path_within(inferred_case, case_root)
            
        )
        in_scope = (
            entry_targets_case(entry, case_root)
            or inferred_in_scope
            or entry.pid in launcher_pids
            or has_ancestor(entry.pid, launcher_pids, table)
        )
        if require_case_target and not in_scope:
            continue
        if role == "launcher" and not launcher_has_solver_descendant(
            entry.pid,
            table,
            solver_name,
        ):
            continue
        processes.append(
            {
                "pid": entry.pid,
                "ppid": entry.ppid,
                "solver": solver or guess_solver_from_args(entry.args),
                "role": role,
                "tracked": entry.pid in tracked_pids,
                "case": str(inferred_case) if inferred_case is not None else None,
                "command": " ".join(entry.args),
            },
        )
    processes.sort(key=lambda item: int(item.get("pid", 0)))
    return processes


def proc_table(proc_root: Path) -> dict[int, ProcEntry]:
    table: dict[int, ProcEntry] = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return table
    for entry in entries:
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        pid = int(entry.name)
        args = read_proc_args(entry)
        ppid = read_proc_ppid(entry)
        cwd = proc_cwd(entry)
        table[pid] = ProcEntry(pid=pid, ppid=ppid, args=args, cwd=cwd)
    return table


def launcher_pids_for_case(
    table: dict[int, ProcEntry],
    solver: str | None,
    case_path: Path,
) -> set[int]:
    launcher_pids: set[int] = set()
    for entry in table.values():
        if not entry.args:
            continue
        base = Path(entry.args[0]).name.lower()
        if base not in _MPI_LAUNCHERS:
            continue
        targeted = entry_targets_case(entry, case_path) or launcher_descendant_targets_case(
            entry.pid,
            table,
            case_path,
        )
        if not targeted:
            continue
        if solver is None:
            if launcher_has_solver_descendant(entry.pid, table, None):
                launcher_pids.add(entry.pid)
            continue
        if any(token_matches_solver(arg, solver) for arg in entry.args):
            launcher_pids.add(entry.pid)
            continue
        if launcher_has_solver_descendant(entry.pid, table, solver):
            launcher_pids.add(entry.pid)
    return launcher_pids


def launcher_has_solver_descendant(
    pid: int,
    table: dict[int, ProcEntry],
    solver: str | None,
) -> bool:
    for child in table.values():
        if not has_ancestor(child.pid, {pid}, table):
            continue
        if process_role(child.args, solver) == "solver":
            return True
    return False


def has_ancestor(pid: int, ancestors: set[int], table: dict[int, ProcEntry]) -> bool:
    seen: set[int] = set()
    cur = pid
    while cur not in seen:
        seen.add(cur)
        entry = table.get(cur)
        if entry is None:
            return False
        if entry.ppid in ancestors:
            return True
        if entry.ppid <= 0 or entry.ppid == cur:
            return False
        cur = entry.ppid
    return False


def read_proc_args(proc_dir: Path) -> list[str]:
    cmdline_path = proc_dir / "cmdline"
    try:
        raw = cmdline_path.read_bytes()
    except OSError:
        return []
    if not raw:
        comm = read_proc_comm(proc_dir)
        return [comm] if comm else []
    parts = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part]
    if parts:
        return parts
    comm = read_proc_comm(proc_dir)
    return [comm] if comm else []


def read_proc_comm(proc_dir: Path) -> str | None:
    comm_path = proc_dir / "comm"
    try:
        value = comm_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return None
    if not value:
        return None
    return value


def read_proc_ppid(proc_dir: Path) -> int:
    stat_path = proc_dir / "stat"
    try:
        text = stat_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return -1
    if ") " not in text:
        return -1
    tail = text.split(") ", 1)[1]
    parts = tail.split()
    if len(parts) < 3:
        return -1
    try:
        return int(parts[1])
    except ValueError:
        return -1


def process_role(args: list[str], solver: str | None) -> str | None:
    if not args:
        return None
    base = Path(args[0]).name.lower()
    if base in _MPI_LAUNCHERS:
        return "launcher"
    if solver is None:
        if looks_like_solver_args(args):
            return "solver"
        return None
    if args_match_solver(args, solver):
        return "solver"
    return None


def args_match_solver(args: list[str], solver: str) -> bool:
    solver_name = solver.lower()
    return any(token_matches_solver(arg, solver_name) for arg in args)


def token_matches_solver(text: str, solver: str) -> bool:
    if Path(text).name.lower() == solver:
        return True
    cleaned = text.replace(";", " ").replace("&&", " ")
    return any(Path(token).name.lower() == solver for token in cleaned.split())


def targets_case(proc_dir: Path, args: list[str], case_path: Path) -> bool:
    entry = ProcEntry(pid=-1, ppid=-1, args=args, cwd=proc_cwd(proc_dir))
    return entry_targets_case(entry, case_path.resolve())


def entry_targets_case(entry: ProcEntry, case_path: Path) -> bool:
    resolved_case = case_path.resolve()
    if entry.cwd is not None and path_within(entry.cwd, resolved_case):
        return True
    for idx, arg_value in enumerate(entry.args):
        if arg_value != "-case":
            continue
        if idx + 1 >= len(entry.args):
            continue
        candidate = Path(entry.args[idx + 1]).expanduser()
        if candidate.is_absolute():
            resolved_candidate = candidate.resolve()
        else:
            base = entry.cwd if entry.cwd is not None else resolved_case
            resolved_candidate = (base / candidate).resolve()
        if path_within(resolved_candidate, resolved_case):
            return True
    return False


def infer_case_path(entry: ProcEntry, table: dict[int, ProcEntry]) -> Path | None:
    checked: set[Path] = set()
    cursor: ProcEntry | None = entry
    depth = 0
    while cursor is not None and depth < 12:
        candidate = case_candidate_from_args(cursor.args, cursor.cwd)
        resolved = as_case_dir(candidate, checked=checked)
        if resolved is not None:
            return resolved
        if cursor.cwd is not None:
            resolved = as_case_dir(cursor.cwd, checked=checked)
            if resolved is not None:
                return resolved
        parent_pid = cursor.ppid
        if parent_pid <= 0 or parent_pid == cursor.pid:
            break
        cursor = table.get(parent_pid)
        depth += 1
    return None


def case_candidate_from_args(args: list[str], cwd: Path | None) -> Path | None:
    for idx, arg_value in enumerate(args):
        if arg_value != "-case":
            continue
        if idx + 1 >= len(args):
            continue
        raw = Path(args[idx + 1]).expanduser()
        if raw.is_absolute():
            return raw
        if cwd is not None:
            return (cwd / raw).resolve()
        return raw.resolve()
    return None


def as_case_dir(path: Path | None, *, checked: set[Path] | None = None) -> Path | None:
    if path is None:
        return None
    resolved = path.resolve()
    visited = checked if checked is not None else set()
    for candidate in [resolved, *resolved.parents[:8]]:
        if candidate in visited:
            continue
        visited.add(candidate)
        if is_case_dir(candidate):
            return candidate
    return None


def is_case_dir(path: Path) -> bool:
    return (path / "system" / "controlDict").is_file()


def proc_cwd(proc_dir: Path) -> Path | None:
    cwd_link = proc_dir / "cwd"
    try:
        return cwd_link.resolve()
    except OSError:
        return None


def launcher_descendant_targets_case(
    pid: int,
    table: dict[int, ProcEntry],
    case_path: Path,
) -> bool:
    for child in table.values():
        if not has_ancestor(child.pid, {pid}, table):
            continue
        if entry_targets_case(child, case_path):
            return True
    return False


def path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def looks_like_solver_args(args: list[str]) -> bool:
    for arg in args:
        token = Path(arg).name
        if token.endswith("Foam"):
            return True
    return False


def guess_solver_from_args(args: list[str]) -> str:
    for arg in args:
        token = Path(arg).name
        if token.endswith("Foam"):
            return token
    return "unknown"
