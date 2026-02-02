from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from ofti.foam.config import get_config
from ofti.tools.helpers import resolve_openfoam_bashrc, with_bashrc
from ofti.tools.input_prompts import prompt_command_line
from ofti.tools.job_registry import finish_job, refresh_jobs, register_job
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import (
    _expand_command,
    _expand_shell_command,
    _show_message,
    _with_no_foam_hint,
)
from ofti.tools.tool_catalog import tool_catalog


def run_tool_background_screen(stdscr: Any, case_path: Path) -> None:
    options = _background_tool_catalog(case_path)
    labels = [name for name, _cmd in options] + ["Back"]
    menu = build_menu(
        stdscr,
        "Run tool in background",
        labels,
        menu_key="menu:job_start",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    name, cmd = options[choice]
    if name == "[custom] command":
        cmd = prompt_command_line(stdscr, "Command line: ")
        if cmd is None:
            return
        name = cmd[0]
    _start_background_command(stdscr, case_path, name, cmd)


def stop_job_screen(stdscr: Any, case_path: Path) -> None:
    jobs = [job for job in refresh_jobs(case_path) if job.get("status") == "running"]
    if not jobs:
        _show_message(stdscr, "No running jobs to stop.")
        return
    labels = [f"{job.get('name','job')} pid={job.get('pid','?')}" for job in jobs] + [
        "Back",
    ]
    menu = build_menu(
        stdscr,
        "Stop job",
        labels,
        menu_key="menu:job_stop",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    job = jobs[choice]
    pid = job.get("pid")
    if not isinstance(pid, int):
        _show_message(stdscr, "Invalid job pid.")
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        finish_job(case_path, str(job.get("id", "")), "missing", None)
        _show_message(stdscr, f"Failed to stop pid {pid}: {exc}")
        return
    finish_job(case_path, str(job.get("id", "")), "stopped", None)
    _show_message(stdscr, f"Sent SIGTERM to pid {pid}.")


def _background_tool_catalog(case_path: Path) -> list[tuple[str, list[str]]]:
    base = tool_catalog(case_path)
    custom = [("[custom] command", [])]
    return base + custom


def _start_background_command(
    stdscr: Any,
    case_path: Path,
    name: str,
    cmd: list[str],
) -> None:
    expanded = _expand_command(cmd, case_path)
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if wm_dir and get_config().use_runfunctions:
        cmd_str = " ".join(shlex.quote(part) for part in expanded)
        shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; runApplication {cmd_str}'
        _start_background_shell(stdscr, case_path, name, shell_cmd)
        return

    bashrc = resolve_openfoam_bashrc()
    if bashrc:
        shell_cmd = " ".join(shlex.quote(part) for part in expanded)
        _start_background_shell(stdscr, case_path, name, shell_cmd)
        return

    try:
        process = _popen_background(expanded, case_path, name)
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return
    register_job(case_path, name, process.pid, " ".join(expanded), _log_path(case_path, name))
    _show_message(stdscr, f"Started {name} (pid {process.pid}).")


def start_tool_background(stdscr: Any, case_path: Path, name: str, cmd: list[str]) -> None:
    _start_background_command(stdscr, case_path, name, cmd)


def _start_background_shell(
    stdscr: Any,
    case_path: Path,
    name: str,
    shell_cmd: str,
) -> None:
    shell_cmd = with_bashrc(_expand_shell_command(shell_cmd, case_path))
    try:
        process = _popen_background(["bash", "--noprofile", "--norc", "-c", shell_cmd], case_path, name)
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return
    register_job(case_path, name, process.pid, shell_cmd, _log_path(case_path, name))
    _show_message(stdscr, f"Started {name} (pid {process.pid}).")


def _popen_background(cmd: list[str], case_path: Path, name: str) -> subprocess.Popen[str]:
    log_path = _log_path(case_path, name)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8", errors="ignore")
    return subprocess.Popen(  # noqa: S603
        cmd,
        cwd=case_path,
        stdout=handle,
        stderr=handle,
        text=True,
    )


def _log_path(case_path: Path, name: str) -> Path:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", "."))
    return case_path / f"log.{safe or 'tool'}"
