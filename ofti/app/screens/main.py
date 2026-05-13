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
from ofti.app.screens.cockpit import cockpit_screen
from ofti.app.state import AppState, Screen
from ofti.core.case_meta import case_metadata, case_metadata_quick
from ofti.foam.config import fzf_enabled
from ofti.tools.navigation_service import root_nav_item, root_nav_labels
from ofti.ui.help import main_menu_help, menu_hint
from ofti.ui.menu import RootMenu
from ofti.ui_curses.layout import (
    ascii_meter,
    case_banner_lines,
    case_overview_lines,
    compact_case_banner_lines,
    status_chip,
)
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

    categories = root_nav_labels()
    menu_options = list(categories)
    quit_index = len(menu_options)
    menu_options.append("Quit")

    height, width = stdscr.getmaxyx() if hasattr(stdscr, "getmaxyx") else (24, 80)
    compact = height < 22 or width < 88
    banner_meta = case_metadata_cached(case_path, state)
    overview_lines = case_overview_lines(banner_meta, compact=compact)
    banner_lines = (
        compact_case_banner_lines(banner_meta, width)
        if compact
        else case_banner_lines(banner_meta)
    )
    initial_index = state.menu_selection.get("menu:root", 0)
    root_menu = RootMenu(
        stdscr,
        "OFTI menu",
        menu_options,
        extra_lines=overview_lines,
        banner_lines=banner_lines,
        initial_index=initial_index,
        command_handler=lambda cmd: handle_command(
            stdscr, case_path, state, cmd, command_callbacks,
        ),
        command_suggestions=lambda: command_suggestions(case_path),
        hint_provider=lambda idx: menu_hint("menu:root", menu_options[idx])
        if 0 <= idx < len(menu_options)
        else "",
        inspector_provider=lambda idx: _root_inspector(
            menu_options[idx],
            banner_meta,
            compact=compact,
        ),
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

    def config_action(title: str) -> Callable[[], Screen]:
        return lambda: config_menu(
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
            title=title,
        )

    def simulation_action(title: str) -> Callable[[], Screen]:
        return lambda: simulation_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
            title=title,
        )

    actions: dict[str, Callable[[], Screen | None]] = {
        "Captains Deck": lambda: _overview_action(stdscr, case_path, state),
        "Prepare": config_action("Prepare"),
        "Mesh": lambda: mesh_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        ),
        "Physics": lambda: physics_menu(
            stdscr,
            case_path,
            state,
            editor_screen,
            check_syntax_screen,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        ),
        "Numerics": config_action("Numerics"),
        "Launch": simulation_action("Launch"),
        "Flight": simulation_action("Flight"),
        "Analyze": lambda: postprocessing_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        ),
        "Case Ops": lambda: clean_case_menu(
            stdscr,
            case_path,
            state,
            command_handler=menu_command,
            command_suggestions=menu_suggestions,
        ),
    }
    if 0 <= choice < len(categories):
        return actions[categories[choice]]()
    return Screen.MAIN_MENU


def _overview_action(stdscr: Any, case_path: Path, state: AppState) -> Screen | None:
    return cockpit_screen(stdscr, case_path, state)


def _root_inspector(label: str, meta: dict[str, str], *, compact: bool) -> list[str]:
    nav_item = root_nav_item(label)
    status = meta.get("status", "unknown")
    title = f"[{nav_item.mode}] {label}"
    lines = [
        "+- Selection --------------------------------",
        f"| {title}",
        "|",
        f"| focus   {nav_item.focus}",
        f"| safety  {nav_item.safety}",
        "|",
        f"| case    {meta.get('case_name', 'unknown')}",
        f"| solver  {meta.get('solver', 'unknown')}",
        f"| state   {status_chip(status)} {status}",
        f"| latest  {meta.get('latest_time', 'n/a')}",
    ]
    if not compact:
        lines.extend(
            [
                f"| mesh    {meta.get('mesh', 'unknown')}",
                f"| disk    {meta.get('disk', 'n/a')}",
                f"| health  {ascii_meter(_status_score(status))}",
            ],
        )
    lines.extend(
        [
            "|",
            "| actions",
            *[f"| - {action}" for action in nav_item.actions[:3]],
            "|",
            f"| {nav_item.detail}",
            f"| hint: {nav_item.hint}",
            "+-------------------------------------------",
        ],
    )
    return lines


def _status_score(status: str | None) -> float:
    text = str(status or "").lower()
    if text in {"ok", "clean", "ready", "ran", "done", "pass", "passed"}:
        return 1.0
    if text in {"running", "run"}:
        return 0.75
    if text in {"warn", "warning", "caution"}:
        return 0.45
    if text in {"error", "fail", "failed", "crit", "critical"}:
        return 0.1
    return 0.25

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
