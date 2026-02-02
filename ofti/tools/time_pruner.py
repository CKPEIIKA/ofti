from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.times import time_directories
from ofti.tools.runner import _show_message
from ofti.ui_curses.inputs import prompt_input


def time_directory_pruner_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901
    times = time_directories(case_path)
    if len(times) < 2:
        _show_message(stdscr, "No time directories found to prune.")
        return

    stdscr.clear()
    raw = prompt_input(stdscr, "Keep every Nth time directory (e.g. 10): ")
    if raw is None:
        return
    raw = raw.strip()
    if not raw:
        return
    try:
        interval = int(raw)
    except ValueError:
        _show_message(stdscr, f"Invalid number: {raw}")
        return
    if interval <= 1:
        _show_message(stdscr, "Interval must be >= 2 to prune.")
        return

    keep: set[Path] = set()
    for idx, path in enumerate(times):
        if idx % interval == 0:
            keep.add(path)
    keep.add(times[-1])

    removed = 0
    for path in times:
        if path in keep:
            continue
        try:
            for child in path.rglob("*"):
                if child.is_file():
                    child.unlink()
            path.rmdir()
            removed += 1
        except OSError:
            continue

    _show_message(stdscr, f"Removed {removed} time directories.")
