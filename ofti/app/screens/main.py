from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ofti.app.clean_menu import clean_case_menu
from ofti.app.commands import CommandCallbacks, command_suggestions, handle_command
from ofti.app.menu_utils import root_status_line
from ofti.app.menus.config import config_menu
from ofti.app.menus.mesh import mesh_menu
from ofti.app.menus.physics import physics_menu
from ofti.app.menus.postprocessing import postprocessing_menu
from ofti.app.menus.simulation import simulation_menu
from ofti.app.state import AppState, Screen
from ofti.core.case_meta import case_metadata, case_metadata_quick
from ofti.foam.config import fzf_enabled
from ofti.tools.menus import tools_screen
from ofti.ui_curses.help import main_menu_help, menu_hint
from ofti.ui_curses.layout import case_banner_lines, case_overview_lines
from ofti.ui_curses.menus import RootMenu
from ofti.ui_curses.openfoam_env import openfoam_env_screen

EditorScreen = Callable[[Any, Path, AppState], None]
CheckScreen = Callable[[Any, Path, AppState], None]
SearchScreen = Callable[[Any, Path, AppState], None]


def main_menu_screen(  # noqa: C901
    stdscr: Any,
    case_path: Path,
    state: AppState,
    *,
    command_callbacks: CommandCallbacks,
    editor_screen: EditorScreen,
    check_syntax_screen: CheckScreen,
    global_search_screen: SearchScreen,
) -> Screen | None:
    state.transition(Screen.MAIN_MENU)
    has_fzf = fzf_enabled()

    categories = [
        "Mesh",
        "Physics & Boundary Conditions",
        "Simulation",
        "Post-Processing",
        "Clean case",
        "Config Manager",
        "Tools",
    ]
    menu_options = list(categories)
    quit_index = len(menu_options)
    menu_options.append("Quit")

    overview_lines = case_overview_lines(case_metadata_cached(case_path, state))
    initial_index = state.menu_selection.get("menu:root", 0)
    root_menu = RootMenu(
        stdscr,
        "Main menu",
        menu_options,
        extra_lines=overview_lines,
        banner_provider=lambda: case_banner_lines(case_metadata_cached(case_path, state)),
        initial_index=initial_index,
        command_handler=lambda cmd: handle_command(
            stdscr, case_path, state, cmd, command_callbacks,
        ),
        command_suggestions=lambda: command_suggestions(case_path),
        hint_provider=lambda idx: menu_hint("menu:root", menu_options[idx])
        if 0 <= idx < len(menu_options)
        else "",
        status_line=root_status_line(state),
        help_lines=main_menu_help(),
    )
    def menu_command(cmd: str) -> str | None:
        return handle_command(stdscr, case_path, state, cmd, command_callbacks)

    def menu_suggestions() -> list[str]:
        return command_suggestions(case_path)
    choice = root_menu.navigate()
    if choice in (-1, quit_index):
        return None
    state.menu_selection["menu:root"] = choice

    if choice == 0:
        return mesh_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        )
    if choice == 1:
        return physics_menu(
            stdscr,
            case_path,
            state,
            editor_screen,
            check_syntax_screen,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        )
    if choice == 2:
        return simulation_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        )
    if choice == 3:
        return postprocessing_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        )
    if choice == 4:
        return clean_case_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        )
    if choice == 5:
        return config_menu(
            stdscr,
            case_path,
            state,
            has_fzf,
            editor_screen,
            check_syntax_screen,
            openfoam_env_screen,
            global_search_screen,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        )
    if choice == 6:
        tools_screen(
            stdscr,
            case_path,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        )
        return Screen.MAIN_MENU
    return Screen.MAIN_MENU


def case_metadata_cached(case_path: Path, state: AppState) -> dict[str, str]:
    if case_path != state.case_metadata_path:
        state.case_metadata_path = case_path
        state.case_metadata = case_metadata_quick(case_path)
        return state.case_metadata or {}
    if state.case_metadata is None:
        state.case_metadata = case_metadata_quick(case_path)
        return state.case_metadata or {}
    return state.case_metadata


def refresh_case_metadata(case_path: Path, state: AppState) -> dict[str, str]:
    state.case_metadata_path = case_path
    state.case_metadata = case_metadata(case_path)
    return state.case_metadata or {}
