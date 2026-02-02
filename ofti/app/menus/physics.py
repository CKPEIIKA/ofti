from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.menu_utils import menu_choice
from ofti.app.state import AppState, Screen
from ofti.ui_curses.boundary_matrix import boundary_matrix_screen
from ofti.ui_curses.help import physics_help
from ofti.ui_curses.initial_conditions import initial_conditions_screen
from ofti.ui_curses.thermo_wizard import thermophysical_wizard_screen


def physics_menu(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    editor_screen: Any,
    check_syntax_screen: Any,
    *,
    command_handler: Any | None = None,
    command_suggestions: Any | None = None,
) -> Screen:
    options = [
        "Config Editor",
        "Boundary matrix",
        "Initial conditions",
        "Thermophysical wizard",
        "Check syntax",
        "Back",
    ]
    actions = [
        lambda: editor_screen(stdscr, case_path, state),
        lambda: boundary_matrix_screen(stdscr, case_path),
        lambda: initial_conditions_screen(stdscr, case_path),
        lambda: thermophysical_wizard_screen(stdscr, case_path),
        lambda: check_syntax_screen(stdscr, case_path, state),
    ]
    while True:
        choice = menu_choice(
            stdscr,
            "Physics & Boundary Conditions",
            options,
            state,
            "menu:physics",
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            help_lines=physics_help(),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if 0 <= choice < len(actions):
            actions[choice]()
