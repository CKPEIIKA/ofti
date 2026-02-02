from __future__ import annotations

import curses
from contextlib import suppress
from pathlib import Path
from typing import Any

from ofti.core.tool_output import CommandResult, format_command_result
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.subprocess_utils import run_trusted
from ofti.tools.job_registry import refresh_jobs
from ofti.tools.runner import _run_shell_tool, _run_simple_tool, _show_message, get_last_tool_run
from ofti.ui_curses.help import menu_hint
from ofti.ui_curses.layout import status_message
from ofti.ui_curses.menus import Menu
from ofti.ui_curses.viewer import Viewer


def job_status_poll_screen(stdscr: Any, case_path: Path) -> None:
    """Show OFTI-tracked jobs (no external foamCheckJobs/foamPrintJobs)."""
    stdscr.timeout(800)
    try:
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            back_hint = key_hint("back", "h")
            header = f"Job status ({back_hint} to exit)"
            with suppress(curses.error):
                stdscr.addstr(header[: max(1, width - 1)] + "\n\n")

            jobs = refresh_jobs(case_path)
            if not jobs:
                with suppress(curses.error):
                    stdscr.addstr("No tracked jobs in this case.\n")
            else:
                for job in sorted(jobs, key=lambda j: j.get("started_at", 0), reverse=True):
                    if stdscr.getyx()[0] >= height - 2:
                        break
                    name = str(job.get("name", "job"))
                    pid = job.get("pid", "?")
                    status = str(job.get("status", "unknown"))
                    log_path = job.get("log") or ""
                    line = f"{name} pid={pid} {status}"
                    if log_path:
                        line = f"{line} | {Path(str(log_path)).name}"
                    with suppress(curses.error):
                        stdscr.addstr(line[: max(1, width - 1)] + "\n")

            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), ord("h")):
                return
            if key_in(key, get_config().keys.get("quit", [])):
                return
            if key_in(key, get_config().keys.get("back", [])):
                return
    finally:
        stdscr.timeout(-1)


def run_shell_script_screen(stdscr: Any, case_path: Path) -> None:
    """Discover and run *.sh scripts in the case directory."""
    scripts = sorted(p for p in case_path.glob("*.sh") if p.is_file())
    if not scripts:
        _show_message(stdscr, "No *.sh scripts found in case directory.")
        return

    labels = [p.name for p in scripts]
    menu = Menu(
        stdscr,
        "Select script to run",
        [*labels, "Back"],
        hint_provider=lambda idx: (
            "Run selected script."
            if 0 <= idx < len(labels)
            else menu_hint("menu:script_select", "Back")
        ),
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    path = scripts[choice]
    status_message(stdscr, f"Running {path.name}...")
    try:
        result = run_trusted(
            ["sh", str(path)],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, f"Failed to run {path.name}: {exc}")
        return

    summary = format_command_result(
        [f"$ cd {case_path}", f"$ sh {path.name}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


def rerun_last_tool(stdscr: Any, case_path: Path) -> None:
    last = get_last_tool_run()
    if last is None:
        _show_message(stdscr, "No previous tool run recorded.")
        return
    if last.kind == "shell":
        _run_shell_tool(stdscr, case_path, f"Re-run {last.name}", str(last.command))
    else:
        _run_simple_tool(stdscr, case_path, f"Re-run {last.name}", list(last.command))
