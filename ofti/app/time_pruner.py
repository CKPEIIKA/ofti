from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.times import time_directories
from ofti.tools.runner import _show_message
from ofti.ui_curses.prompts import prompt_line


def time_directory_pruner_screen(stdscr: Any, case_path: Path) -> None:
    times = time_directories(case_path)
    if len(times) < 2:
        _show_message(stdscr, "No time directories found to prune.")
        return

    stdscr.clear()
    interval = _prompt_interval(stdscr)
    if interval is None:
        return
    removed = _prune_times(times, interval)
    _show_message(stdscr, f"Removed {removed} time directories.")


def _prompt_interval(stdscr: Any) -> int | None:
    raw = prompt_line(stdscr, "Keep every Nth time directory (e.g. 10): ")
    if raw is None or not raw:
        return None
    try:
        interval = int(raw)
    except ValueError:
        _show_message(stdscr, f"Invalid number: {raw}")
        return None
    if interval <= 1:
        _show_message(stdscr, "Interval must be >= 2 to prune.")
        return None
    return interval


def _prune_times(times: list[Path], interval: int) -> int:
    keep = {path for idx, path in enumerate(times) if idx % interval == 0}
    keep.add(times[-1])
    removed = 0
    for path in times:
        if path not in keep and _remove_time_dir(path):
            removed += 1
    return removed


def _remove_time_dir(path: Path) -> bool:
    try:
        for child in path.rglob("*"):
            if child.is_file():
                child.unlink()
        path.rmdir()
    except OSError:
        return False
    return True
