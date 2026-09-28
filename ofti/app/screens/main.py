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
from ofti.app.overview import running_header_metadata
from ofti.app.screens.overview import overview_screen
from ofti.app.state import AppState, Screen
from ofti.core.case_meta import case_metadata, case_metadata_quick
from ofti.foam.config import fzf_enabled
from ofti.ui.help import main_menu_help, menu_hint
from ofti.ui.menu import RootMenu
from ofti.ui_curses.layout import case_banner_lines, case_overview_lines
from ofti.ui_curses.openfoam_env import openfoam_env_screen

EditorScreen = Callable[[Any, Path, AppState], None]
CheckScreen = Callable[[Any, Path, AppState], None]
SearchScreen = Callable[[Any, Path, AppState], None]


def main_menu_screen(
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
        "Overview",
        "Mesh",
        "Physics & Boundary Conditions",
        "Simulation",
        "Post-Processing",
        "Clean case",
        "Config Manager",
    ]
    menu_options = list(categories)
    quit_index = len(menu_options)
    menu_options.append("Quit")

    banner = _RootBanner(case_path, state)

    def root_command(cmd: str) -> str | None:
        result = handle_command(stdscr, case_path, state, cmd, command_callbacks)
        # Commands can run tools or solvers; refresh the header afterwards.
        banner.invalidate()
        return result

    initial_index = state.menu_selection.get("menu:root", 0)
    root_menu = RootMenu(
        stdscr,
        "Main menu",
        menu_options,
        extra_lines=case_overview_lines({}),
        banner_provider=banner.lines,
        initial_index=initial_index,
        command_handler=root_command,
        command_suggestions=lambda: command_suggestions(case_path),
        hint_provider=lambda idx: menu_hint("menu:root", menu_options[idx]) if 0 <= idx < len(menu_options) else "",
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

    actions = [
        lambda: _overview_action(stdscr, case_path),
        lambda: mesh_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        ),
        lambda: physics_menu(
            stdscr,
            case_path,
            state,
            editor_screen,
            check_syntax_screen,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        ),
        lambda: simulation_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        ),
        lambda: postprocessing_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        ),
        lambda: clean_case_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        ),
        lambda: config_menu(
            stdscr,
            case_path,
            state,
            has_fzf=has_fzf,
            editor_screen=editor_screen,
            check_syntax_screen=check_syntax_screen,
            openfoam_env_screen=openfoam_env_screen,
            global_search_screen=global_search_screen,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        ),
    ]
    if 0 <= choice < len(actions):
        next_screen = actions[choice]()
        # Actions mutate the case (mesh, run, clean); re-read the header next time.
        banner.invalidate()
        return next_screen
    return Screen.MAIN_MENU


class _RootBanner:
    """Case header cached between key presses; process scans are not per-key cheap."""

    def __init__(self, case_path: Path, state: AppState) -> None:
        self._case_path = case_path
        self._state = state
        self._lines: list[str] | None = None

    def lines(self) -> list[str]:
        if self._lines is None:
            meta = case_metadata_cached(self._case_path, self._state)
            self._lines = case_banner_lines(running_header_metadata(self._case_path, meta))
        return self._lines

    def invalidate(self) -> None:
        self._state.case_metadata = None
        self._lines = None


def _overview_action(stdscr: Any, case_path: Path) -> Screen:
    overview_screen(stdscr, case_path)
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
