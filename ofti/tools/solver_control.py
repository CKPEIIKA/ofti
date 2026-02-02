from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.case import set_start_from_latest
from ofti.core.times import latest_time
from ofti.tools.runner import _show_message


def safe_stop_screen(stdscr: Any, case_path: Path) -> None:
    stop_file = case_path / "stop"
    try:
        stop_file.write_text("")
    except OSError as exc:
        _show_message(stdscr, f"Failed to create stop file: {exc}")
        return
    _show_message(stdscr, "Created stop file. Solver will stop after next write.")


def solver_resurrection_screen(stdscr: Any, case_path: Path) -> None:
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        _show_message(stdscr, "system/controlDict not found.")
        return
    latest = latest_time(case_path)
    if latest in ("0", "0.0", ""):
        _show_message(stdscr, "No latest time found to resume from.")
        return
    if set_start_from_latest(control_dict, latest):
        _show_message(stdscr, f"Set startFrom latestTime and startTime {latest}.")
        return
    _show_message(stdscr, "Failed to update controlDict (check OpenFOAM env).")
