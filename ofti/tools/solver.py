from __future__ import annotations

import curses
import os
import shutil
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any

from ofti.core.case import read_number_of_subdomains
from ofti.core.solver_checks import (
    remove_empty_log,
    resolve_solver_name,
    truncate_log,
    validate_initial_fields,
)
from ofti.core.solver_status import (
    fatal_log_line,
    last_courant_value,
    last_solver_time,
    latest_solver_job,
    residual_spark_lines,
    solver_status_text,
)
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.subprocess_utils import resolve_executable
from ofti.tools.cleaning_utils import _require_wm_project_dir
from ofti.tools.helpers import resolve_openfoam_bashrc, with_bashrc
from ofti.tools.job_registry import finish_job, register_job
from ofti.tools.runner import (
    _expand_shell_command,
    _run_simple_tool,
    _show_message,
    _with_no_foam_hint,
)

require_wm_project_dir = _require_wm_project_dir


def run_current_solver(stdscr: Any, case_path: Path) -> None:
    solver, error = resolve_solver_name(case_path)
    if error:
        _show_message(stdscr, _with_no_foam_hint(error))
        return
    if not _ensure_zero_dir(stdscr, case_path):
        return
    errors = validate_initial_fields(case_path)
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
        truncate_log(log_path)
    _run_simple_tool(
        stdscr,
        case_path,
        solver,
        [solver],
        allow_runfunctions=False,
    )


def run_current_solver_live(stdscr: Any, case_path: Path) -> None:
    """Run the solver and tail its log file live with a split-screen view."""
    solver, error = resolve_solver_name(case_path)
    if error:
        _show_message(stdscr, _with_no_foam_hint(error))
        return
    if not _ensure_zero_dir(stdscr, case_path):
        return
    errors = validate_initial_fields(case_path)
    if errors:
        _show_message(stdscr, "\n".join(["Cannot run solver:", *errors]))
        return

    log_path = case_path / f"log.{solver}"
    if log_path.exists():
        if remove_empty_log(log_path):
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
            truncate_log(log_path)

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
    if log_path.exists() and not remove_empty_log(log_path):
        stdscr.clear()
        stdscr.addstr(
            f"Log {log_path.name} already exists. Rerun solver and overwrite log? [y/N]: ",
        )
        stdscr.refresh()
        ch = stdscr.getch()
        if ch not in (ord("y"), ord("Y")):
            return
        truncate_log(log_path)
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
    solver, _ = resolve_solver_name(case_path)
    if not solver:
        return None
    summary = latest_solver_job(case_path, solver)
    if summary is None:
        return None
    return solver_status_text(summary)


def solver_job_running(case_path: Path) -> bool:
    solver, _ = resolve_solver_name(case_path)
    if not solver:
        return False
    summary = latest_solver_job(case_path, solver)
    return summary is not None and summary.status == "running"


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
            last_time = last_solver_time(lines)
            last_courant = last_courant_value(lines)

            stdscr.clear()
            height, width = stdscr.getmaxyx()
            back_hint = key_hint("back", "h")
            running = process.poll() is None
            status = "running" if running else "finished"
            header = f"{solver} ({status})  {back_hint}: {'stop' if running else 'back'}"
            with suppress(curses.error):
                stdscr.addstr(header[: max(1, width - 1)] + "\n")
            fatal_line = fatal_log_line(lines)
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
            residual_lines = residual_spark_lines(lines, width)
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


def _prepare_parallel_run(
    stdscr: Any,
    case_path: Path,
) -> tuple[str, int] | None:
    solver, error = resolve_solver_name(case_path)
    if error:
        _show_message(stdscr, _with_no_foam_hint(error))
        return None
    if not _ensure_zero_dir(stdscr, case_path):
        return None
    errors = validate_initial_fields(case_path)
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


 


def _clean_env(case_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    env["PWD"] = str(case_path.resolve())
    return env


    return env
