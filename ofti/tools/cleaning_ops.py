from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.foam.config import get_config
from ofti.tools.cleaning_utils import _require_wm_project_dir
from ofti.tools.runner import _run_shell_tool, _show_message


def remove_all_logs(
    stdscr: Any,
    case_path: Path,
    *,
    silent: bool = False,
    use_cleanfunctions: bool = True,
) -> None:
    """Remove log.* files using CleanFunctions helpers."""
    wm_dir = _require_wm_project_dir(stdscr) if use_cleanfunctions else None
    if use_cleanfunctions and wm_dir and get_config().use_cleanfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanApplicationLogs'
        _run_shell_tool(stdscr, case_path, "cleanApplicationLogs", shell_cmd)
        return

    removed = 0
    for path in case_path.glob("log.*"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    if not silent:
        _show_message(stdscr, f"Removed {removed} log files.")


def clean_time_directories(
    stdscr: Any,
    case_path: Path,
    *,
    silent: bool = False,
    use_cleanfunctions: bool = True,
) -> None:
    """Remove time directories using CleanFunctions."""
    wm_dir = _require_wm_project_dir(stdscr) if use_cleanfunctions else None
    if use_cleanfunctions and wm_dir and get_config().use_cleanfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanTimeDirectories'
        _run_shell_tool(stdscr, case_path, "cleanTimeDirectories", shell_cmd)
        return

    removed = 0
    for entry in case_path.iterdir():
        if not entry.is_dir():
            continue
        if entry.name == "0":
            continue
        try:
            value = float(entry.name)
        except ValueError:
            continue
        if value < 0:
            continue
        try:
            for child in entry.rglob("*"):
                if child.is_file():
                    child.unlink()
            entry.rmdir()
            removed += 1
        except OSError:
            continue
    if not silent:
        _show_message(stdscr, f"Removed {removed} time directories.")

