from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.menu_utils import menu_choice
from ofti.app.state import AppState, Screen
from ofti.tools.cleaning_ops import clean_time_directories, remove_all_logs
from ofti.tools.reconstruct import reconstruct_latest_once
from ofti.tools.runner import _show_message
from ofti.tools.time_pruner import time_directory_pruner_screen
from ofti.ui_curses.help import clean_case_help
from ofti.ui_curses.layout import status_message


def clean_case_menu(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    *,
    command_handler: Any | None = None,
    command_suggestions: Any | None = None,
) -> Screen:
    options = [
        "Clean all",
        "Remove all logs",
        "Clean time directories",
        "Clear parallel",
        "Time directory pruner",
        "Back",
    ]
    disabled = set(range(len(options) - 1)) if state.no_foam else None
    while True:
        choice = menu_choice(
            stdscr,
            "Clean case",
            options,
            state,
            "menu:clean",
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            disabled_indices=disabled,
            help_lines=clean_case_help(),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            clean_all(stdscr, case_path)
        elif choice == 1:
            remove_all_logs(stdscr, case_path)
        elif choice == 2:
            clean_time_directories(stdscr, case_path)
        elif choice == 3:
            clear_parallel(stdscr, case_path)
        elif choice == 4:
            time_directory_pruner_screen(stdscr, case_path)


def clean_all(stdscr: Any, case_path: Path) -> None:
    status_message(stdscr, "Cleaning logs...")
    remove_all_logs(stdscr, case_path, silent=True, use_cleanfunctions=False)
    status_message(stdscr, "Cleaning time directories...")
    clean_time_directories(stdscr, case_path, silent=True, use_cleanfunctions=False)
    status_message(stdscr, "Removing processor directories...")
    _remove_processor_dirs(case_path)
    _show_message(stdscr, "Clean all complete.")


def clear_parallel(stdscr: Any, case_path: Path) -> None:
    status_message(stdscr, "Removing processor directories...")
    _remove_processor_dirs(case_path)
    status_message(stdscr, "Reconstructing latest time...")
    _ok, note = reconstruct_latest_once(case_path)
    summary = "Parallel cleanup complete."
    if note:
        summary = f"{summary} {note}"
    _show_message(stdscr, summary)


def _remove_processor_dirs(case_path: Path) -> int:
    removed = 0
    for entry in case_path.iterdir():
        if entry.is_dir() and entry.name.startswith("processor"):
            try:
                for child in entry.rglob("*"):
                    if child.is_file():
                        child.unlink()
                entry.rmdir()
                removed += 1
            except OSError:
                continue
    return removed
