from __future__ import annotations

import curses
import os
import shutil
import signal
import subprocess
import time
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
from ofti.core.tool_output import CommandResult, format_command_result
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.subprocess_utils import resolve_executable
from ofti.foamlib.logs import read_log_tail_lines
from ofti.tools import watch_service
from ofti.tools.cleaning_utils import _require_wm_project_dir
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.helpers import resolve_openfoam_bashrc
from ofti.tools.input_prompts import prompt_line
from ofti.tools.job_registry import finish_job
from ofti.tools.runner import (
    _expand_shell_command,
    _show_message,
    _with_no_foam_hint,
)
from ofti.ui_curses.viewer import Viewer

require_wm_project_dir = _require_wm_project_dir


def run_current_solver(stdscr: Any, case_path: Path) -> None:
    solver, error = resolve_solver_name(case_path)
    if error:
        _show_message(stdscr, _with_no_foam_hint(error))
        return
    if solver is None:
        _show_message(stdscr, _with_no_foam_hint("Could not determine solver name."))
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
    try:
        result = run_ops.execute_case_command(
            case_path,
            solver,
            [solver],
            background=False,
        )
    except ValueError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {solver}: {exc}"))
        return

    summary = format_command_result(
        [f"$ cd {case_path}", f"$ {solver}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
    )
    Viewer(stdscr, summary).display()


def run_current_solver_live(stdscr: Any, case_path: Path) -> None:
    """Run the solver and tail its log file live with a split-screen view."""
    solver = _prepare_solver_run(stdscr, case_path)
    if solver is None:
        return
    log_path = _prepare_solver_log_path(stdscr, case_path, solver)
    if log_path is None:
        return
    _run_current_solver_live_with_log(stdscr, case_path, solver, log_path)


def run_current_solver_live_custom_log(stdscr: Any, case_path: Path) -> None:
    solver = _prepare_solver_run(stdscr, case_path)
    if solver is None:
        return
    stdscr.clear()
    raw_log_path = prompt_line(stdscr, f"Log path inside case (default log.{solver}): ")
    if raw_log_path is None:
        return
    log_path = _prepare_solver_log_path(stdscr, case_path, solver, raw_log_path)
    if log_path is None:
        return
    _run_current_solver_live_with_log(stdscr, case_path, solver, log_path)


def _run_current_solver_live_with_log(
    stdscr: Any,
    case_path: Path,
    solver: str,
    log_path: Path,
) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _show_message(stdscr, f"Failed to create log directory {log_path.parent}: {exc}")
        return

    bashrc = resolve_openfoam_bashrc()
    if bashrc:
        shell_cmd = solver
        _run_solver_live_shell(stdscr, case_path, solver, shell_cmd, log_path=log_path)
        return

    _run_solver_live_cmd(stdscr, case_path, solver, [solver], log_path=log_path)


def run_current_solver_parallel(stdscr: Any, case_path: Path) -> None:
    setup = _prepare_parallel_run(stdscr, case_path)
    if setup is None:
        return
    solver, subdomains = setup
    if _prepare_solver_log_path(stdscr, case_path, solver) is None:
        return
    mpi_exec = _resolve_mpi_launcher(stdscr)
    if not mpi_exec:
        return
    try:
        _display, cmd = run_ops.solver_command(
            case_path,
            solver=solver,
            parallel=subdomains,
            mpi=mpi_exec,
            sync_subdomains=False,
        )
    except ValueError:
        cmd = [mpi_exec, "-np", str(subdomains), solver, "-parallel"]
    _run_solver_live_cmd(stdscr, case_path, solver, cmd)


class _TrackedJobProcess:
    def __init__(self, case_path: Path, pid: int, job_id: str | None) -> None:
        self._case_path = case_path
        self._pid = int(pid)
        self._job_id = job_id

    def poll(self) -> int | None:
        if _pid_running(self._pid):
            return None
        return 0

    def terminate(self) -> None:
        if self._job_id:
            with suppress(Exception):
                watch_service.stop_payload(
                    self._case_path,
                    job_id=self._job_id,
                    all_jobs=False,
                    kind="any",
                    signal_name="TERM",
                )
                return
        with suppress(OSError):
            os.kill(self._pid, signal.SIGTERM)

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else (time.monotonic() + timeout)
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(cmd=str(self._pid), timeout=timeout)
            time.sleep(0.05)
        return 0


def _run_solver_live_shell(
    stdscr: Any,
    case_path: Path,
    solver: str,
    shell_cmd: str,
    *,
    log_path: Path | None = None,
) -> None:
    command = _expand_shell_command(shell_cmd, case_path)
    _run_solver_live_cmd(
        stdscr,
        case_path,
        solver,
        ["bash", "--noprofile", "--norc", "-c", command],
        log_path=log_path,
    )


def _run_solver_live_cmd(
    stdscr: Any,
    case_path: Path,
    solver: str,
    cmd: list[str],
    *,
    log_path: Path | None = None,
) -> None:
    target_log = log_path if log_path is not None else case_path / f"log.{solver}"
    target_log.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        target_log.write_text("")
    try:
        payload = watch_service.start_payload(
            case_path,
            name=solver,
            command=cmd,
            detached=False,
            log_file=str(target_log),
            kind="solver",
        )
    except ValueError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {solver}: {exc}"))
        return
    pid = payload.get("pid")
    if not isinstance(pid, int):
        _show_message(stdscr, f"Failed to run {solver}: missing background pid")
        return
    job_id_raw = payload.get("job_id")
    job_id = str(job_id_raw).strip() if job_id_raw is not None else ""
    process = _TrackedJobProcess(case_path, pid, job_id or None)
    _tail_process_log(
        stdscr,
        case_path,
        solver,
        process,
        target_log,
        job_id or None,
    )


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


def _tail_process_log(
    stdscr: Any,
    case_path: Path,
    solver: str,
    process: Any,
    log_path: Path,
    job_id: str | None,
) -> None:
    cfg = get_config()
    patterns = ["FATAL", "bounding", "Courant", "nan", "SIGFPE", "floating point exception"]
    stdscr.timeout(400)
    stopped_by_user = False
    try:
        while True:
            try:
                lines = read_log_tail_lines(log_path, max_lines=600)
            except OSError:
                lines = []
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
                stopped_by_user = True
                process.terminate()
                with suppress(Exception):
                    process.wait(timeout=5)
                return
    finally:
        returncode = process.poll()
        if stopped_by_user or returncode is None:
            finish_job(case_path, job_id, "stopped", None)
        else:
            finish_job(case_path, job_id, "finished", int(returncode))
        stdscr.timeout(-1)


def _prepare_parallel_run(
    stdscr: Any,
    case_path: Path,
) -> tuple[str, int] | None:
    solver = _prepare_solver_run(stdscr, case_path)
    if solver is None:
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


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _clean_env(case_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    env["PWD"] = str(case_path.resolve())
    return env


def _prepare_solver_run(stdscr: Any, case_path: Path) -> str | None:
    solver, error = resolve_solver_name(case_path)
    if error:
        _show_message(stdscr, _with_no_foam_hint(error))
        return None
    if solver is None:
        _show_message(stdscr, _with_no_foam_hint("Could not determine solver name."))
        return None
    if not _ensure_zero_dir(stdscr, case_path):
        return None
    errors = validate_initial_fields(case_path)
    if errors:
        _show_message(stdscr, "\n".join(["Cannot run solver:", *errors]))
        return None
    return solver


def _prepare_solver_log_path(
    stdscr: Any,
    case_path: Path,
    solver: str,
    raw_log_path: str | None = None,
) -> Path | None:
    try:
        log_path = _resolve_solver_log_path(case_path, solver, raw_log_path)
    except ValueError as exc:
        _show_message(stdscr, str(exc))
        return None
    if log_path.exists() and not remove_empty_log(log_path):
        try:
            shown_log = log_path.relative_to(case_path.resolve())
        except ValueError:
            shown_log = log_path
        stdscr.clear()
        stdscr.addstr(
            f"Log {shown_log} already exists. Rerun solver and overwrite log? [y/N]: ",
        )
        stdscr.refresh()
        ch = stdscr.getch()
        if ch not in (ord("y"), ord("Y")):
            return None
        truncate_log(log_path)
    return log_path


def _resolve_solver_log_path(
    case_path: Path,
    solver: str,
    raw_log_path: str | None,
) -> Path:
    raw = (raw_log_path or "").strip()
    relative_path = Path(raw) if raw else Path(f"log.{solver}")
    if relative_path.is_absolute():
        raise ValueError("Log path must be relative to the case directory.")
    resolved_case = case_path.resolve()
    resolved_log = (resolved_case / relative_path).resolve()
    try:
        resolved_log.relative_to(resolved_case)
    except ValueError as exc:
        raise ValueError("Log path must stay inside the case directory.") from exc
    return resolved_log
