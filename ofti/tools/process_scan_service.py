from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

_MPI_LAUNCHERS = {"mpirun", "mpiexec", "mpiexec.hydra", "orterun", "srun"}
_SHELL_LAUNCHERS = {"bash", "sh", "zsh", "dash", "ksh"}
_DISCOVERY_CACHE_TTL_SECONDS = 600.0


@dataclass(frozen=True)
class ProcessCaseCacheEntry:
    pid: int
    ppid: int
    command_head: str
    case: Path
    source: str
    timestamp: float
    proc_root: Path


@dataclass(frozen=True)
class ProcessCaseDiscovery:
    case: Path | None
    source: str
    error: str
    launcher_pid: int | None


@dataclass(frozen=True)
class ProcEntry:
    pid: int
    ppid: int
    args: list[str]
    cwd: Path | None
    cwd_error: str | None = None


class ProcRow(TypedDict, total=False):
    pid: int
    ppid: int
    solver: str | None
    role: str
    tracked: bool
    case: str
    command: str
    discovery_source: str
    discovery_error: str
    launcher_pid: int | None
    solver_pids: list[int]


_DISCOVERY_CACHE: dict[int, ProcessCaseCacheEntry] = {}


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
    _cleanup_discovery_cache()
    case_root = case_path.resolve()
    case_root_is_case = is_case_dir(case_root)
    solver_name = solver.lower() if solver else None
    launcher_cases = launcher_case_map(table)
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
        discovery = discover_case(
            entry,
            table,
            launcher_cases=launcher_cases,
            proc_root=proc_root,
        )
        inferred_case = discovery.case
        inferred_in_scope = inferred_case is not None and _in_scope_case(
            inferred_case,
            case_root,
            case_root_is_case=case_root_is_case,
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
        row: ProcRow = {
            "pid": entry.pid,
            "ppid": entry.ppid,
            "solver": solver or guess_solver_from_args(entry.args),
            "role": role,
            "tracked": entry.pid in tracked_pids,
            "case": _case_to_text(inferred_case),
            "command": " ".join(entry.args),
            "discovery_source": discovery.source,
            "discovery_error": discovery.error,
            "launcher_pid": discovery.launcher_pid,
        }
        if role == "launcher":
            row["solver_pids"] = solver_descendant_pids(entry.pid, table, solver_name)
        processes.append(row)
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
        cwd, cwd_error = proc_cwd_with_error(entry)
        table[pid] = ProcEntry(pid=pid, ppid=ppid, args=args, cwd=cwd, cwd_error=cwd_error)
    return table


def launcher_pids_for_case(
    table: dict[int, ProcEntry],
    solver: str | None,
    case_path: Path,
) -> set[int]:
    launcher_pids: set[int] = set()
    case_root_is_case = is_case_dir(case_path)
    for entry in table.values():
        if not entry.args:
            continue
        base = Path(entry.args[0]).name.lower()
        if base not in _MPI_LAUNCHERS:
            continue
        inferred_case = infer_case_path(entry, table)
        targeted = (
            entry_targets_case(entry, case_path)
            or launcher_descendant_targets_case(entry.pid, table, case_path)
            or (
                inferred_case is not None
                and _in_scope_case(
                    inferred_case,
                    case_path,
                    case_root_is_case=case_root_is_case,
                )
            )
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


def solver_descendant_pids(
    pid: int,
    table: dict[int, ProcEntry],
    solver: str | None,
) -> list[int]:
    pids: list[int] = []
    for child in table.values():
        if not has_ancestor(child.pid, {pid}, table):
            continue
        if process_role(child.args, solver) != "solver":
            continue
        pids.append(child.pid)
    pids.sort()
    return pids


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
    role: str | None = None
    if base in _MPI_LAUNCHERS or (
        solver is not None
        and base in _SHELL_LAUNCHERS
        and _shell_command_matches_solver(args, solver)
    ):
        role = "launcher"
    elif solver is None:
        if looks_like_solver_args(args):
            role = "solver"
    elif args_match_solver(args, solver):
        role = "solver"
    return role


def args_match_solver(args: list[str], solver: str) -> bool:
    solver_name = solver.lower()
    return any(token_matches_solver(arg, solver_name) for arg in args)


def token_matches_solver(text: str, solver: str) -> bool:
    if Path(text).name.lower() == solver:
        return True
    cleaned = text.replace(";", " ").replace("&&", " ")
    return any(Path(token).name.lower() == solver for token in cleaned.split())


def _shell_command_matches_solver(args: list[str], solver: str) -> bool:
    if not args:
        return False
    base = Path(args[0]).name.lower()
    if base not in _SHELL_LAUNCHERS:
        return False
    solver_name = solver.lower()
    for idx, token in enumerate(args[:-1]):
        if token not in {"-c", "-lc"}:
            continue
        command = args[idx + 1]
        if not command:
            continue
        if token_matches_solver(command, solver_name):
            return True
    return False


def _shell_command_has_any_solver(args: list[str]) -> bool:
    if not args:
        return False
    base = Path(args[0]).name.lower()
    if base not in _SHELL_LAUNCHERS:
        return False
    for idx, token in enumerate(args[:-1]):
        if token not in {"-c", "-lc"}:
            continue
        command = args[idx + 1]
        if not command:
            continue
        cleaned = command.replace(";", " ").replace("&&", " ")
        for part in cleaned.split():
            name = Path(part.strip("'\"")).name
            if name.endswith("Foam"):
                return True
    return False


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
        command_case = case_candidate_from_shell_args(cursor.args, cursor.cwd)
        resolved = as_case_dir(command_case, checked=checked)
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


def case_candidate_from_shell_args(args: list[str], cwd: Path | None) -> Path | None:
    if not args:
        return None
    base = Path(args[0]).name.lower()
    if base not in _SHELL_LAUNCHERS:
        return None
    for idx, token in enumerate(args[:-1]):
        if token not in {"-c", "-lc"}:
            continue
        command = args[idx + 1]
        if not command:
            continue
        candidate = _shell_cd_candidate(command, cwd)
        if candidate is not None:
            return candidate
    return None


def _shell_cd_candidate(command: str, cwd: Path | None) -> Path | None:
    lowered = command.replace("&&", ";")
    chunks = [chunk.strip() for chunk in lowered.split(";")]
    for chunk in chunks:
        if not chunk.startswith("cd "):
            continue
        raw = chunk[3:].strip()
        if not raw:
            continue
        token = raw.split()[0].strip()
        if token.startswith(("'", '"')) and token.endswith(("'", '"')) and len(token) >= 2:
            token = token[1:-1]
        candidate = Path(token).expanduser()
        if candidate.is_absolute():
            return candidate
        if cwd is not None:
            return (cwd / candidate).resolve()
        return candidate.resolve()
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
    try:
        return (path / "system" / "controlDict").is_file()
    except OSError:
        return False


def proc_cwd(proc_dir: Path) -> Path | None:
    cwd, _error = proc_cwd_with_error(proc_dir)
    return cwd


def proc_cwd_with_error(proc_dir: Path) -> tuple[Path | None, str | None]:
    cwd_link = proc_dir / "cwd"
    try:
        return cwd_link.resolve(), None
    except OSError as exc:
        if exc.strerror:
            return None, exc.strerror.lower()
        return None, str(exc).lower()


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


def launcher_case_map(table: dict[int, ProcEntry]) -> dict[int, Path]:
    rows: dict[int, Path] = {}
    for entry in table.values():
        if not entry.args:
            continue
        if Path(entry.args[0]).name.lower() not in _MPI_LAUNCHERS:
            continue
        case_path = infer_case_path(entry, table)
        if case_path is None:
            continue
        rows[entry.pid] = case_path
    return rows


def discover_case(
    entry: ProcEntry,
    table: dict[int, ProcEntry],
    *,
    launcher_cases: dict[int, Path],
    proc_root: Path,
) -> ProcessCaseDiscovery:
    inferred = infer_case_path(entry, table)
    if inferred is not None:
        source = "procfs"
        launcher_pid = launcher_pid_for_entry(entry, table)
        if launcher_pid is not None and entry.pid != launcher_pid:
            source = "launcher"
        _cache_discovery(entry, inferred, source, proc_root=proc_root)
        return ProcessCaseDiscovery(
            case=inferred,
            source=source,
            error="",
            launcher_pid=launcher_pid,
        )
    launcher_pid = launcher_pid_for_entry(entry, table)
    if launcher_pid is not None:
        launcher_case = launcher_cases.get(launcher_pid)
        if launcher_case is not None:
            _cache_discovery(entry, launcher_case, "launcher", proc_root=proc_root)
            return ProcessCaseDiscovery(
                case=launcher_case,
                source="launcher",
                error="",
                launcher_pid=launcher_pid,
            )
    cached = _cache_lookup(entry, proc_root=proc_root)
    if cached is not None:
        return ProcessCaseDiscovery(
            case=cached.case,
            source="registry",
            error="",
            launcher_pid=launcher_pid,
        )
    error = entry.cwd_error or "case_not_found"
    return ProcessCaseDiscovery(
        case=None,
        source="procfs",
        error=error,
        launcher_pid=launcher_pid,
    )


def launcher_pid_for_entry(entry: ProcEntry, table: dict[int, ProcEntry]) -> int | None:
    if entry.args and Path(entry.args[0]).name.lower() in _MPI_LAUNCHERS:
        return entry.pid
    cursor = entry
    visited: set[int] = set()
    while cursor.pid not in visited:
        visited.add(cursor.pid)
        parent_pid = cursor.ppid
        if parent_pid <= 0 or parent_pid == cursor.pid:
            break
        parent = table.get(parent_pid)
        if parent is None:
            break
        if parent.args and Path(parent.args[0]).name.lower() in _MPI_LAUNCHERS:
            return parent.pid
        if _shell_command_has_any_solver(parent.args):
            return parent.pid
        cursor = parent
    return None


def _cache_lookup(entry: ProcEntry, *, proc_root: Path) -> ProcessCaseCacheEntry | None:
    cached = _DISCOVERY_CACHE.get(entry.pid)
    if cached is None:
        return None
    if cached.proc_root != proc_root.resolve():
        return None
    if cached.ppid != entry.ppid:
        return None
    if cached.command_head != _command_head(entry.args):
        return None
    if (time.time() - cached.timestamp) > _DISCOVERY_CACHE_TTL_SECONDS:
        _DISCOVERY_CACHE.pop(entry.pid, None)
        return None
    return cached


def _cache_discovery(entry: ProcEntry, case_path: Path, source: str, *, proc_root: Path) -> None:
    _DISCOVERY_CACHE[entry.pid] = ProcessCaseCacheEntry(
        pid=entry.pid,
        ppid=entry.ppid,
        command_head=_command_head(entry.args),
        case=case_path,
        source=source,
        timestamp=time.time(),
        proc_root=proc_root.resolve(),
    )


def _cleanup_discovery_cache() -> None:
    now = time.time()
    expired = [
        pid
        for pid, row in _DISCOVERY_CACHE.items()
        if (now - row.timestamp) > _DISCOVERY_CACHE_TTL_SECONDS
    ]
    for pid in expired:
        _DISCOVERY_CACHE.pop(pid, None)


def _command_head(args: list[str]) -> str:
    if not args:
        return ""
    return " ".join(args[:4])


def _case_to_text(case_path: Path | None) -> str:
    if case_path is None:
        return ""
    return str(case_path)


def _in_scope_case(case_path: Path, case_root: Path, *, case_root_is_case: bool) -> bool:
    if case_root_is_case:
        return case_path == case_root
    return path_within(case_path, case_root)
