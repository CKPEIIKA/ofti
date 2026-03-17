from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.config_templates import create_missing_config_screen
from ofti.app.menu_utils import menu_choice
from ofti.app.menus.case_tools import (
    compare_dictionaries_screen,
    set_dictionary_entry_screen,
    show_case_status_screen,
    show_initial_fields_screen,
    show_preflight_screen,
)
from ofti.app.state import AppState, Screen
from ofti.foam.config import get_config
from ofti.tools.case_doctor import case_doctor_screen
from ofti.tools.case_ops import clone_case
from ofti.ui_curses.help import config_help


def config_menu(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    has_fzf: bool,
    editor_screen: Any,
    check_syntax_screen: Any,
    openfoam_env_screen: Any,
    global_search_screen: Any,
    *,
    command_handler: Any | None = None,
    command_suggestions: Any | None = None,
) -> Screen:
    options = [
        "Config Editor",
        "Create missing config",
        "Preflight checks",
        "Case doctor",
        "Case status",
        "Initial fields summary",
        "Set dictionary entry",
        "Compare dictionaries",
        "Clone case",
        "OpenFOAM environment",
        "Check syntax",
    ]
    if has_fzf:
        options.append("Search")
    options.append("Back")
    cfg = get_config()
    original_search = list(cfg.keys.get("search", []))
    if "s" not in original_search:
        cfg.keys["search"] = [*original_search, "s"]
    try:
        while True:
            choice = menu_choice(
                stdscr,
                "Config Manager",
                options,
                state,
                "menu:config",
                command_handler=command_handler,
                command_suggestions=command_suggestions,
                help_lines=config_help(),
            )
            if choice in (-1, len(options) - 1):
                return Screen.MAIN_MENU
            if choice == 0:
                editor_screen(stdscr, case_path, state)
            elif choice == 1:
                create_missing_config_screen(stdscr, case_path)
            elif choice == 2:
                show_preflight_screen(stdscr, case_path)
            elif choice == 3:
                case_doctor_screen(stdscr, case_path)
            elif choice == 4:
                show_case_status_screen(stdscr, case_path)
            elif choice == 5:
                show_initial_fields_screen(stdscr, case_path)
            elif choice == 6:
                set_dictionary_entry_screen(stdscr, case_path)
            elif choice == 7:
                compare_dictionaries_screen(stdscr, case_path)
            elif choice == 8:
                clone_case(stdscr, case_path)
            elif choice == 9:
                openfoam_env_screen(stdscr)
            elif choice == 10:
                check_syntax_screen(stdscr, case_path, state)
            elif has_fzf and choice == 11:
                global_search_screen(stdscr, case_path, state)
    finally:
        cfg.keys["search"] = original_search
