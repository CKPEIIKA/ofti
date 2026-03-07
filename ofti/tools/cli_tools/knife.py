from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.dict_compare import compare_case_dicts
from ofti.core.entry_io import write_entry
from ofti.core.solver_checks import resolve_solver_name
from ofti.core.solver_status import latest_solver_job, solver_status_text
from ofti.core.times import latest_time
from ofti.foamlib.logs import execution_time_deltas, parse_log_metrics, parse_residuals
from ofti.tools.case_doctor import build_case_doctor_report
from ofti.tools.job_registry import refresh_jobs

from .common import read_text, require_case_dir, resolve_log_source

_TIME_RE = re.compile(r"^\s*Time\s*=\s*(?P<value>[0-9eE.+-]+)\s*$", re.MULTILINE)
_DELTA_T_RE = re.compile(r"\bdeltaT\s*=\s*(?P<value>[0-9eE.+-]+)", re.IGNORECASE)
_ITER_RE = re.compile(r"\b(?:iteration|iter)\s*[=:]\s*(?P<value>\d+)", re.IGNORECASE)
_END_TIME_RE = re.compile(r"\bendTime\s+(?P<value>[^;]+);")
_START_TIME_RE = re.compile(r"\bstartTime\s+(?P<value>[^;]+);")
_SHOCK_RE = re.compile(r"(?:shock|delta\s*/?\s*d)[^0-9+\-]*(?P<value>[0-9eE.+-]+)", re.IGNORECASE)
_DRAG_RE = re.compile(
    r"(?:\bcd\b|drag(?:\s+coefficient)?)\s*[:=]?\s*(?P<value>[0-9eE.+-]+)",
    re.IGNORECASE,
)
_MASS_RE = re.compile(r"continuity errors.*?global\s*=\s*(?P<value>[0-9eE.+-]+)", re.IGNORECASE)
_CRITERIA_RE = re.compile(
    r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_./:-]*(?:Tolerance|Delta|Band|Target|Max|Min|Drift))\s+"
    r"(?P<value>[^;]+);",
    re.MULTILINE,
)
_KEY_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_./:-]*$")
_MPI_LAUNCHERS = {"mpirun", "mpiexec", "mpiexec.hydra", "orterun", "srun"}


@dataclass(frozen=True)
class ProcEntry:
    pid: int
    ppid: int
    args: list[str]
    cwd: Path | None


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
                "kind": diff.kind,
                "missing_in_left": diff.missing_in_left,
                "missing_in_right": diff.missing_in_right,
                "value_diffs": [
                    {"key": value.key, "left": value.left, "right": value.right}
                    for value in diff.value_diffs
                ],
                "left_hash": diff.left_hash,
                "right_hash": diff.right_hash,
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
    tracked_pids = set(_running_job_pids(running_jobs))
    live_processes: list[dict[str, Any]] = []
    if solver and solver_error is None:
        live_processes = _scan_proc_solver_processes(
            case_path,
            solver,
            tracked_pids=tracked_pids,
            include_tracked=True,
        )
    tracked_live = [row for row in live_processes if bool(row.get("tracked"))]
    untracked_live = [row for row in live_processes if not bool(row.get("tracked"))]

    solver_status: str | None = None
    if solver:
        summary = latest_solver_job(case_path, solver)
        solver_status = solver_status_text(summary) if summary else None

    runtime = _runtime_control_snapshot(case_path, solver)
    latest_time_value = runtime["latest_time"]
    has_live_pids = bool(live_processes)
    running_heuristic = has_live_pids or runtime["log_fresh"]
    return {
        "case": str(case_path),
        "solver": solver,
        "solver_error": solver_error,
        "solver_status": solver_status,
        "latest_time": (
            latest_time_value if latest_time_value is not None else latest_time(case_path)
        ),
        "latest_iteration": runtime["latest_iteration"],
        "latest_delta_t": runtime["latest_delta_t"],
        "sec_per_iter": runtime["sec_per_iter"],
        "run_time_control": runtime["run_time_control"],
        "eta_seconds_to_criteria_start": runtime["eta_to_criteria_start"],
        "eta_seconds_to_end_time": runtime["eta_to_end_time"],
        "log_path": runtime["log_path"],
        "log_fresh": runtime["log_fresh"],
        "running": running_heuristic,
        "jobs_total": len(jobs),
        "jobs_running": len(running_jobs),
        "jobs": jobs,
        "tracked_solver_processes": tracked_live,
        "untracked_solver_processes": untracked_live,
    }


def converge_payload(
    source: Path,
    *,
    strict: bool = False,
    shock_drift_limit: float = 0.02,
    drag_band_limit: float = 0.02,
    mass_limit: float = 1e-4,
) -> dict[str, Any]:
    log_path = resolve_log_source(source)
    text = read_text(log_path)
    lines = text.splitlines()
    residuals = parse_residuals(text)
    shock_values = _collect_floats(lines, _SHOCK_RE)
    drag_values = _collect_floats(lines, _DRAG_RE)
    mass_values = [abs(value) for value in _collect_floats(lines, _MASS_RE)]

    shock_drift = _band(shock_values)
    drag_band = _band(drag_values[-20:])
    mass_last = mass_values[-1] if mass_values else None
    thermo_oob = _thermo_out_of_range_count(lines)
    flatline = _residual_flatline(residuals)

    shock_ok = shock_drift is not None and shock_drift <= shock_drift_limit
    drag_ok = drag_band is not None and drag_band <= drag_band_limit
    mass_ok = mass_last is not None and mass_last <= mass_limit
    thermo_ok = thermo_oob == 0
    strict_ok = shock_ok and drag_ok and mass_ok

    return {
        "log": str(log_path),
        "shock": {
            "count": len(shock_values),
            "last": shock_values[-1] if shock_values else None,
            "drift": shock_drift,
            "limit": shock_drift_limit,
            "ok": shock_ok,
        },
        "drag": {
            "count": len(drag_values),
            "last": drag_values[-1] if drag_values else None,
            "band": drag_band,
            "limit": drag_band_limit,
            "ok": drag_ok,
        },
        "mass": {
            "count": len(mass_values),
            "last_abs_global": mass_last,
            "limit": mass_limit,
            "ok": mass_ok,
        },
        "residuals": {
            "fields": sorted(residuals),
            "flatline_fields": flatline,
            "flatline": bool(flatline),
        },
        "thermo": {
            "out_of_range_count": thermo_oob,
            "ok": thermo_ok,
        },
        "strict": strict,
        "strict_ok": strict_ok,
        "ok": strict_ok if strict else (shock_ok and drag_ok and mass_ok and thermo_ok),
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
    include_tracked: bool = False,
) -> list[dict[str, Any]]:
    table = _proc_table(proc_root)
    case_root = case_path.resolve()
    solver_name = solver.lower()
    launcher_pids = _launcher_pids_for_case(table, solver_name, case_root)
    processes: list[dict[str, Any]] = []
    for entry in table.values():
        if entry.pid in tracked_pids and not include_tracked:
            continue
        if not entry.args:
            continue
        role = _process_role(entry.args, solver_name)
        if role is None:
            continue
        if (
            not _entry_targets_case(entry, case_root)
            and entry.pid not in launcher_pids
            and not _has_ancestor(entry.pid, launcher_pids, table)
        ):
            continue
        if role == "launcher" and not _launcher_has_solver_descendant(
            entry.pid,
            table,
            solver_name,
        ):
            continue
        processes.append(
            {
                "pid": entry.pid,
                "ppid": entry.ppid,
                "solver": solver,
                "role": role,
                "tracked": entry.pid in tracked_pids,
                "command": " ".join(entry.args),
            },
        )
    processes.sort(key=lambda item: int(item.get("pid", 0)))
    return processes


def _proc_table(proc_root: Path) -> dict[int, ProcEntry]:
    table: dict[int, ProcEntry] = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return table
    for entry in entries:
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        pid = int(entry.name)
        args = _read_proc_args(entry)
        ppid = _read_proc_ppid(entry)
        cwd = _proc_cwd(entry)
        table[pid] = ProcEntry(pid=pid, ppid=ppid, args=args, cwd=cwd)
    return table


def _launcher_pids_for_case(table: dict[int, ProcEntry], solver: str, case_path: Path) -> set[int]:
    launcher_pids: set[int] = set()
    for entry in table.values():
        if not entry.args:
            continue
        base = Path(entry.args[0]).name.lower()
        if base not in _MPI_LAUNCHERS:
            continue
        if not _entry_targets_case(entry, case_path):
            continue
        if any(_token_matches_solver(arg, solver) for arg in entry.args):
            launcher_pids.add(entry.pid)
            continue
        if _launcher_has_solver_descendant(entry.pid, table, solver):
            launcher_pids.add(entry.pid)
    return launcher_pids


def _launcher_has_solver_descendant(pid: int, table: dict[int, ProcEntry], solver: str) -> bool:
    for child in table.values():
        if not _has_ancestor(child.pid, {pid}, table):
            continue
        if _process_role(child.args, solver) == "solver":
            return True
    return False


def _has_ancestor(pid: int, ancestors: set[int], table: dict[int, ProcEntry]) -> bool:
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


def _read_proc_args(proc_dir: Path) -> list[str]:
    cmdline_path = proc_dir / "cmdline"
    try:
        raw = cmdline_path.read_bytes()
    except OSError:
        return []
    if not raw:
        return []
    return [part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part]


def _read_proc_ppid(proc_dir: Path) -> int:
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


def _process_role(args: list[str], solver: str) -> str | None:
    if not args:
        return None
    base = Path(args[0]).name.lower()
    if base in _MPI_LAUNCHERS:
        return "launcher"
    if _args_match_solver(args, solver):
        return "solver"
    return None


def _args_match_solver(args: list[str], solver: str) -> bool:
    solver_name = solver.lower()
    return any(_token_matches_solver(arg, solver_name) for arg in args)


def _token_matches_solver(text: str, solver: str) -> bool:
    if Path(text).name.lower() == solver:
        return True
    cleaned = text.replace(";", " ").replace("&&", " ")
    return any(Path(token).name.lower() == solver for token in cleaned.split())


def _targets_case(proc_dir: Path, args: list[str], case_path: Path) -> bool:
    entry = ProcEntry(pid=-1, ppid=-1, args=args, cwd=_proc_cwd(proc_dir))
    return _entry_targets_case(entry, case_path.resolve())


def _entry_targets_case(entry: ProcEntry, case_path: Path) -> bool:
    resolved_case = case_path.resolve()
    if entry.cwd == resolved_case:
        return True
    for idx, arg_value in enumerate(entry.args):
        if arg_value != "-case":
            continue
        if idx + 1 >= len(entry.args):
            continue
        candidate = Path(entry.args[idx + 1]).expanduser()
        if candidate == resolved_case:
            return True
        if not candidate.is_absolute():
            base = entry.cwd if entry.cwd is not None else resolved_case
            if (base / candidate).resolve() == resolved_case:
                return True
    return False


def _proc_cwd(proc_dir: Path) -> Path | None:
    cwd_link = proc_dir / "cwd"
    try:
        return cwd_link.resolve()
    except OSError:
        return None


def _runtime_control_snapshot(case_path: Path, solver: str | None) -> dict[str, Any]:
    log_path = _resolve_solver_log(case_path, solver)
    text = read_text(log_path) if log_path is not None else ""
    metrics = parse_log_metrics(text) if text else parse_log_metrics("")
    residuals = parse_residuals(text) if text else {}
    deltas = execution_time_deltas(metrics.execution_times)
    latest_time_value = metrics.times[-1] if metrics.times else None
    latest_delta_t = _last_float(text, _DELTA_T_RE)
    latest_iteration = _latest_iteration(text, len(metrics.times))
    sec_per_iter = (sum(deltas[-8:]) / len(deltas[-8:])) if deltas else None
    run_time_control = _run_time_control_data(case_path, text)
    eta_to_end = _eta_seconds(
        latest_time_value,
        run_time_control.get("end_time"),
        metrics.times,
        metrics.execution_times,
    )
    eta_to_start = _eta_seconds(
        latest_time_value,
        run_time_control.get("criteria_start"),
        metrics.times,
        metrics.execution_times,
    )
    return {
        "log_path": str(log_path) if log_path is not None else None,
        "log_fresh": _is_log_fresh(log_path),
        "latest_time": latest_time_value,
        "latest_iteration": latest_iteration,
        "latest_delta_t": latest_delta_t,
        "sec_per_iter": sec_per_iter,
        "run_time_control": run_time_control,
        "eta_to_end_time": eta_to_end,
        "eta_to_criteria_start": eta_to_start,
        "residual_fields": sorted(residuals),
    }


def _resolve_solver_log(case_path: Path, solver: str | None) -> Path | None:
    if solver:
        candidate = case_path / f"log.{solver}"
        if candidate.is_file():
            return candidate.resolve()
    try:
        return resolve_log_source(case_path)
    except ValueError:
        return None


def _run_time_control_data(case_path: Path, log_text: str) -> dict[str, Any]:
    control_dict = case_path / "system" / "controlDict"
    try:
        text = control_dict.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {
            "end_time": None,
            "criteria_start": None,
            "criteria": [],
            "passed": 0,
            "failed": 0,
            "unknown": 0,
        }
    end_time = _to_float(_first_match(text, _END_TIME_RE))
    start_time = _to_float(_first_match(text, _START_TIME_RE))
    criteria: list[dict[str, Any]] = []
    for match in _CRITERIA_RE.finditer(text):
        key = match.group("key")
        if not _KEY_TOKEN_RE.match(key):
            continue
        value = match.group("value").strip()
        status, evidence = _criterion_status(key, log_text)
        criteria.append({"key": key, "value": value, "status": status, "evidence": evidence})
    passed = sum(1 for row in criteria if row["status"] == "pass")
    failed = sum(1 for row in criteria if row["status"] == "fail")
    unknown = len(criteria) - passed - failed
    return {
        "end_time": end_time,
        "criteria_start": start_time,
        "criteria": criteria,
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
    }


def _criterion_status(key: str, log_text: str) -> tuple[str, str | None]:
    needle = key.lower()
    for raw in reversed(log_text.splitlines()):
        line = raw.strip()
        lower = line.lower()
        if needle not in lower:
            continue
        if any(token in lower for token in ("not satisfied", "fail", "failed", "false", "exceed")):
            return "fail", line
        if any(token in lower for token in ("satisfied", "pass", "passed", "true", "ok")):
            return "pass", line
        return "unknown", line
    return "unknown", None


def _eta_seconds(
    latest_time_value: float | None,
    target_time: float | None,
    times: list[float],
    execution_times: list[float],
) -> float | None:
    if latest_time_value is None or target_time is None:
        return None
    if target_time <= latest_time_value:
        return 0.0
    if len(times) < 2 or len(execution_times) < 2:
        return None
    window = min(len(times), len(execution_times), 8)
    time_delta = times[-1] - times[-window]
    exec_delta = execution_times[-1] - execution_times[-window]
    if time_delta <= 0 or exec_delta <= 0:
        return None
    speed = time_delta / exec_delta
    if speed <= 0:
        return None
    return (target_time - latest_time_value) / speed


def _is_log_fresh(log_path: Path | None, freshness_seconds: float = 90.0) -> bool:
    if log_path is None:
        return False
    try:
        mtime = log_path.stat().st_mtime
    except OSError:
        return False
    return (time.time() - mtime) <= freshness_seconds


def _latest_iteration(text: str, fallback: int) -> int | None:
    match_values = [int(match.group("value")) for match in _ITER_RE.finditer(text)]
    if match_values:
        return match_values[-1]
    if fallback > 0:
        return fallback
    return None


def _first_match(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return match.group("value").strip()


def _last_float(text: str, pattern: re.Pattern[str]) -> float | None:
    values = [match.group("value") for match in pattern.finditer(text)]
    if not values:
        return None
    return _to_float(values[-1])


def _to_float(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().strip(";")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _collect_floats(lines: list[str], pattern: re.Pattern[str]) -> list[float]:
    values: list[float] = []
    for line in lines:
        match = pattern.search(line)
        if match is None:
            continue
        value = _to_float(match.group("value"))
        if value is not None:
            values.append(value)
    return values


def _band(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values) - min(values)


def _thermo_out_of_range_count(lines: list[str]) -> int:
    count = 0
    for line in lines:
        lower = line.lower()
        if "out of range" not in lower:
            continue
        if any(
            token in lower
            for token in ("thermo", "temperature", "enthalpy", "cp", "mu", "rho")
        ):
            count += 1
    return count


def _residual_flatline(residuals: dict[str, list[float]]) -> list[str]:
    flat: list[str] = []
    for field, values in residuals.items():
        if len(values) < 4:
            continue
        head = max(values[:4])
        tail_window = values[-4:]
        tail_max = max(tail_window)
        tail_min = min(tail_window)
        if head <= 0:
            continue
        improved = head / max(tail_max, 1e-30)
        if improved < 2.0 or abs(tail_max - tail_min) <= max(1e-12, tail_max * 0.05):
            flat.append(field)
    return sorted(flat)
