from __future__ import annotations

import curses
import os
import shutil
import subprocess
from contextlib import suppress
from math import log10
from pathlib import Path
from typing import Any

from ofti.core.boundary import list_field_files
from ofti.core.case import read_number_of_subdomains
from ofti.core.checkmesh import extract_last_courant
from ofti.core.entry_io import read_entry
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.openfoam import OpenFOAMError
from ofti.foam.subprocess_utils import resolve_executable
from ofti.foamlib.logs import parse_residuals
from ofti.tools.cleaning_utils import _require_wm_project_dir
from ofti.tools.helpers import resolve_openfoam_bashrc, with_bashrc
from ofti.tools.job_registry import finish_job, refresh_jobs, register_job
from ofti.tools.runner import (
    _expand_shell_command,
    _run_simple_tool,
    _show_message,
    _with_no_foam_hint,
)

require_wm_project_dir = _require_wm_project_dir


def run_current_solver(stdscr: Any, case_path: Path) -> None:
    solver, error = _resolve_solver_name(case_path)
    if error:
        _show_message(stdscr, _with_no_foam_hint(error))
        return
    if not _ensure_zero_dir(stdscr, case_path):
        return
    errors = _validate_initial_fields(case_path)
    if errors:
        _show_message(stdscr, "\n".join(["Cannot run solver:", *errors]))
        return
    log_path = case_path / f"log.{solver}"
    if log_path.exists():
        stdscr.clear()
        stdscr.addstr(
            f"Log {log_path.name} already exists. Rerun solver and overwrite log? [y/N]: ",
        )
        stdscr.refresh()
        ch = stdscr.getch()
        if ch not in (ord("y"), ord("Y")):
            return
        _truncate_log(log_path)
    _run_simple_tool(
        stdscr,
        case_path,
        solver,
        [solver],
        allow_runfunctions=False,
    )


def run_current_solver_live(stdscr: Any, case_path: Path) -> None:
    """Run the solver and tail its log file live with a split-screen view."""
    solver, error = _resolve_solver_name(case_path)
    if error:
        _show_message(stdscr, _with_no_foam_hint(error))
        return
    if not _ensure_zero_dir(stdscr, case_path):
        return
    errors = _validate_initial_fields(case_path)
    if errors:
        _show_message(stdscr, "\n".join(["Cannot run solver:", *errors]))
        return

    log_path = case_path / f"log.{solver}"
    if log_path.exists():
        if _remove_empty_log(log_path):
            pass
        else:
            stdscr.clear()
            stdscr.addstr(
                f"Log {log_path.name} already exists. Rerun solver and overwrite log? [y/N]: ",
            )
            stdscr.refresh()
            ch = stdscr.getch()
            if ch not in (ord("y"), ord("Y")):
                return
            _truncate_log(log_path)

    bashrc = resolve_openfoam_bashrc()
    if bashrc:
        shell_cmd = solver
        _run_solver_live_shell(stdscr, case_path, solver, shell_cmd)
        return

    _run_solver_live_cmd(stdscr, case_path, solver, [solver])


def run_current_solver_parallel(stdscr: Any, case_path: Path) -> None:
    setup = _prepare_parallel_run(stdscr, case_path)
    if setup is None:
        return
    solver, subdomains = setup
    log_path = case_path / f"log.{solver}"
    if log_path.exists() and not _remove_empty_log(log_path):
        stdscr.clear()
        stdscr.addstr(
            f"Log {log_path.name} already exists. Rerun solver and overwrite log? [y/N]: ",
        )
        stdscr.refresh()
        ch = stdscr.getch()
        if ch not in (ord("y"), ord("Y")):
            return
        _truncate_log(log_path)
    mpi_exec = _resolve_mpi_launcher(stdscr)
    if not mpi_exec:
        return
    cmd = [mpi_exec, "-np", str(subdomains), solver, "-parallel"]
    _run_solver_live_cmd(stdscr, case_path, solver, cmd)


def _run_solver_live_shell(stdscr: Any, case_path: Path, solver: str, shell_cmd: str) -> None:
    command = with_bashrc(_expand_shell_command(shell_cmd, case_path))
    log_path = case_path / f"log.{solver}"
    with suppress(OSError):
        log_path.write_text("")
    with log_path.open("a", encoding="utf-8", errors="ignore") as handle:
        try:
            bash_path = resolve_executable("bash")
        except FileNotFoundError as exc:
            _show_message(stdscr, _with_no_foam_hint(f"Failed to run {solver}: {exc}"))
            return
        process = subprocess.Popen(  # noqa: S603
            [bash_path, "--noprofile", "--norc", "-c", command],
            cwd=case_path,
            stdout=handle,
            stderr=handle,
            text=True,
            env=_clean_env(case_path),
        )
        job_id = register_job(case_path, solver, process.pid, command, log_path)
        _tail_process_log(stdscr, case_path, solver, process, log_path, job_id)


def _run_solver_live_cmd(
    stdscr: Any,
    case_path: Path,
    solver: str,
    cmd: list[str],
) -> None:
    log_path = case_path / f"log.{solver}"
    with suppress(OSError):
        log_path.write_text("")
    with log_path.open("a", encoding="utf-8", errors="ignore") as handle:
        process = subprocess.Popen(  # noqa: S603
            cmd,
            cwd=case_path,
            stdout=handle,
            stderr=handle,
            text=True,
            env=_clean_env(case_path),
        )
        job_id = register_job(case_path, solver, process.pid, " ".join(cmd), log_path)
        _tail_process_log(stdscr, case_path, solver, process, log_path, job_id)


def solver_status_line(case_path: Path) -> str | None:
    solver, _ = _resolve_solver_name(case_path)
    if not solver:
        return None
    jobs = refresh_jobs(case_path)
    solver_jobs = [job for job in jobs if job.get("name") == solver]
    if not solver_jobs:
        return None
    last = max(solver_jobs, key=lambda job: job.get("started_at") or 0)
    status = last.get("status", "unknown")
    if status == "running":
        return f"{solver} running"
    if status == "finished":
        rc = last.get("returncode")
        if rc is None:
            text = f"{solver} finished"
        elif rc == 0:
            text = f"{solver} last exit 0"
        else:
            text = f"{solver} failed (exit {rc})"
        return text
    return f"{solver} {status}"


def solver_job_running(case_path: Path) -> bool:
    solver, _ = _resolve_solver_name(case_path)
    if not solver:
        return False
    jobs = refresh_jobs(case_path)
    return any(
        job.get("name") == solver and job.get("status") == "running" for job in jobs
    )


def _resolve_solver_name(case_path: Path) -> tuple[str | None, str | None]:
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        return None, "system/controlDict not found in case directory."
    try:
        value = read_entry(control_dict, "application")
    except OpenFOAMError as exc:
        return None, f"Failed to read application: {exc}"
    solver_line = value.strip()
    if not solver_line:
        return None, "application entry is empty."
    solver = solver_line.split()[0].rstrip(";")
    if not solver:
        return None, "Could not determine solver from application entry."
    return solver, None


def _ensure_zero_dir(stdscr: Any, case_path: Path) -> bool:
    zero_dir = case_path / "0"
    zero_orig = case_path / "0.orig"
    if zero_dir.is_dir():
        return True
    if not zero_orig.is_dir():
        return True
    stdscr.clear()
    stdscr.addstr("0/ directory is missing, but 0.orig exists.\n")
    stdscr.addstr("Copy 0.orig -> 0 and continue? [y/N]: ")
    stdscr.refresh()
    ch = stdscr.getch()
    if ch not in (ord("y"), ord("Y")):
        return False
    try:
        shutil.copytree(zero_orig, zero_dir, symlinks=True)
    except OSError as exc:
        _show_message(stdscr, f"Failed to copy 0.orig -> 0: {exc}")
        return False
    return True


def _validate_initial_fields(case_path: Path) -> list[str]:
    errors: list[str] = []
    zero_dir = case_path / "0"
    zero_orig = case_path / "0.orig"
    if not zero_dir.is_dir():
        if zero_orig.is_dir():
            errors.append("0/ directory missing (only 0.orig present). Copy 0.orig -> 0 first.")
        else:
            errors.append("Missing 0/ initial conditions directory.")
            return errors
    fields = list_field_files(case_path)
    if not fields:
        errors.append("No field files detected in 0/ (or 0.orig).")
        return errors
    required = {"U", "p"}
    missing = sorted(required - set(fields))
    if missing:
        folder_name = "0" if zero_dir.is_dir() else "0.orig"
        errors.append(f"Missing fields in {folder_name}: {', '.join(missing)}")
    return errors


def _tail_process_log(  # noqa: C901, PLR0912
    stdscr: Any,
    case_path: Path,
    solver: str,
    process: subprocess.Popen[str],
    log_path: Path,
    job_id: str | None,
) -> None:
    cfg = get_config()
    patterns = ["FATAL", "bounding", "Courant", "nan", "SIGFPE", "floating point exception"]
    stdscr.timeout(400)
    try:
        while True:
            try:
                text = log_path.read_text(errors="ignore")
            except OSError:
                text = ""
            lines = text.splitlines()
            tail = lines[-12:]
            last_time = _extract_last_time(lines)
            last_courant = extract_last_courant(lines)

            stdscr.clear()
            height, width = stdscr.getmaxyx()
            back_hint = key_hint("back", "h")
            running = process.poll() is None
            status = "running" if running else "finished"
            header = f"{solver} ({status})  {back_hint}: {'stop' if running else 'back'}"
            with suppress(curses.error):
                stdscr.addstr(header[: max(1, width - 1)] + "\n")
            fatal_line = _find_fatal_line(lines)
            returncode = process.poll()
            if returncode is not None and returncode != 0:
                error_line = f"ERROR: exit {returncode}"
                if fatal_line:
                    error_line = f"{error_line} | {fatal_line}"
                with suppress(curses.error):
                    stdscr.addstr(error_line[: max(1, width - 1)] + "\n")
            summary = ""
            if last_time is not None:
                summary = f"Time = {last_time}"
            if last_courant is not None:
                if summary:
                    summary = f"{summary} | Courant: {last_courant:g}"
                else:
                    summary = f"Courant: {last_courant:g}"
            if summary:
                with suppress(curses.error):
                    stdscr.addstr(summary[: max(1, width - 1)] + "\n")
            residual_lines = _residual_spark_lines(lines, width)
            for line in residual_lines:
                with suppress(curses.error):
                    stdscr.addstr(line[: max(1, width - 1)] + "\n")
            with suppress(curses.error):
                stdscr.addstr("-" * max(1, width - 1) + "\n")

            for line in tail:
                if stdscr.getyx()[0] >= height - 1:
                    break
                mark = ""
                if any(pat.lower() in line.lower() for pat in patterns):
                    mark = "!! "
                    with suppress(curses.error):
                        stdscr.attron(curses.A_BOLD)
                try:
                    stdscr.addstr((mark + line)[: max(1, width - 1)] + "\n")
                except curses.error:
                    break
                if mark:
                    with suppress(curses.error):
                        stdscr.attroff(curses.A_BOLD)

            stdscr.refresh()
            if process.poll() is not None:
                stdscr.timeout(-1)
                stdscr.getch()
                return
            key = stdscr.getch()
            if key_in(key, cfg.keys.get("back", [])):
                process.terminate()
                process.wait(timeout=5)
                return
    finally:
        returncode = process.poll()
        if returncode is None:
            finish_job(case_path, job_id, "stopped", None)
        else:
            finish_job(case_path, job_id, "finished", returncode)
        stdscr.timeout(-1)


def _extract_last_time(lines: list[str]) -> str | None:
    for line in reversed(lines):
        if "Time =" in line:
            parts = line.split("Time =", 1)
            if len(parts) == 2:
                return parts[1].strip().split()[0]
    return None


def _find_fatal_line(lines: list[str]) -> str | None:
    markers = [
        "FOAM FATAL ERROR",
        "FATAL ERROR",
        "Cannot open file",
        "cannot open file",
        "cannot find file",
        "No such file",
        "file: ",
    ]
    for line in reversed(lines):
        for marker in markers:
            if marker in line:
                return line.strip()
    return None


def _prepare_parallel_run(
    stdscr: Any,
    case_path: Path,
) -> tuple[str, int] | None:
    solver, error = _resolve_solver_name(case_path)
    if error:
        _show_message(stdscr, _with_no_foam_hint(error))
        return None
    if not _ensure_zero_dir(stdscr, case_path):
        return None
    errors = _validate_initial_fields(case_path)
    if errors:
        _show_message(stdscr, "\n".join(["Cannot run solver:", *errors]))
        return None
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        _show_message(
            stdscr,
            "Missing system/decomposeParDict. Create it in Config Manager first.",
        )
        return None
    subdomains = read_number_of_subdomains(decompose_dict)
    if not subdomains or subdomains <= 0:
        _show_message(
            stdscr,
            "numberOfSubdomains missing or invalid in decomposeParDict.",
        )
        return None
    return solver, subdomains


def _resolve_mpi_launcher(stdscr: Any) -> str | None:
    try:
        return resolve_executable("mpirun")
    except FileNotFoundError:
        try:
            return resolve_executable("mpiexec")
        except FileNotFoundError as exc:
            _show_message(stdscr, _with_no_foam_hint(f"MPI launcher not found: {exc}"))
            return None


def _residual_spark_lines(lines: list[str], width: int) -> list[str]:
    residuals = parse_residuals("\n".join(lines))
    if not residuals:
        return []
    plot_width = max(10, min(30, width - 28))
    preferred = ["p", "U", "Ux", "Uy", "Uz", "k", "omega", "epsilon"]
    ordered = [field for field in preferred if field in residuals]
    ordered += sorted(field for field in residuals if field not in ordered)
    lines_out: list[str] = []
    for field in ordered[:2]:
        values = residuals.get(field, [])
        if not values:
            continue
        plot = _sparkline(values, plot_width)
        last = values[-1]
        lines_out.append(f"Res {field:>6} {plot} last={last:.2g}")
    return lines_out


def _sparkline(values: list[float], width: int) -> str:
    if not values or width <= 0:
        return ""
    if len(values) <= width:
        sample = values
    else:
        step = len(values) / width
        sample = [values[int(i * step)] for i in range(width)]

    safe = [val if val > 0 else 1e-16 for val in sample]
    vmin = min(safe)
    vmax = max(safe)
    if vmax <= 0:
        vmax = 1e-16
    ratio = vmax / vmin if vmin > 0 else vmax
    if ratio > 1e3:
        scaled = [log10(val) for val in safe]
        vmin = min(scaled)
        vmax = max(scaled)
    else:
        scaled = safe

    levels = " .:-=+*#%@"
    span = vmax - vmin
    if span <= 0:
        return levels[-1] * len(sample)
    chars = []
    for val in scaled:
        norm = (val - vmin) / span
        idx = round(norm * (len(levels) - 1))
        idx = max(0, min(len(levels) - 1, idx))
        chars.append(levels[idx])
    return "".join(chars)


def _remove_empty_log(log_path: Path) -> bool:
    try:
        if log_path.stat().st_size == 0:
            log_path.unlink()
            return True
    except OSError:
        pass
    return False


def _truncate_log(log_path: Path) -> None:
    try:
        log_path.write_text("")
    except OSError:
        with suppress(OSError):
            log_path.unlink()


def _clean_env(case_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    env["PWD"] = str(case_path.resolve())
    return env


    return env
