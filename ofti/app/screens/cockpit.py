from __future__ import annotations

import curses
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from ofti.app.overview import (
    cockpit_lines,
    cockpit_panel_detail_lines,
    cockpit_panel_names,
    overview_text,
)
from ofti.app.state import AppState, Screen
from ofti.foam.config import get_config, key_in
from ofti.ui_curses.layout import draw_status_bar
from ofti.ui_curses.viewer import Viewer

_REFRESH_SECONDS = 5.0
_INPUT_TIMEOUT_MS = 250


def cockpit_screen(stdscr: Any, case_path: Path, state: AppState) -> Screen | None:
    """Show the default read-only captains deck screen."""
    state.transition(Screen.COCKPIT, action="cockpit")
    start_line = 0
    selected_panel = 0
    lines: list[str] = []
    last_refresh = 0.0
    last_size: tuple[int, int] | None = None
    needs_refresh = True
    if hasattr(stdscr, "timeout"):
        stdscr.timeout(_INPUT_TIMEOUT_MS)

    try:
        while True:
            height, width = stdscr.getmaxyx()
            size = (height, width)
            now = time.monotonic()
            if (
                needs_refresh
                or last_size != size
                or now - last_refresh >= _REFRESH_SECONDS
            ):
                lines = cockpit_lines(
                    case_path,
                    max(60, width - 1),
                    selected_panel=selected_panel,
                )
                last_refresh = now
                last_size = size
                needs_refresh = False
            visible = max(1, height - 1)
            start_line = min(start_line, max(0, len(lines) - visible))

            _draw_cockpit(stdscr, lines, start_line, visible, width)

            key = stdscr.getch()
            action = _key_action(key)
            if action is None:
                continue
            if action == "quit":
                return None
            if action == "menu":
                return Screen.MAIN_MENU
            panel_action = _handle_panel_action(stdscr, case_path, selected_panel, action)
            if panel_action is not None:
                selected_panel = panel_action
                needs_refresh = True
                continue
            if action == "refresh":
                needs_refresh = True
                continue
            start_line = _scroll_start_line(
                action,
                start_line,
                line_count=len(lines),
                visible=visible,
            )
    finally:
        if hasattr(stdscr, "timeout"):
            stdscr.timeout(-1)


def _handle_panel_action(
    stdscr: Any,
    case_path: Path,
    selected_panel: int,
    action: str,
) -> int | None:
    names = cockpit_panel_names()
    if action == "next_panel":
        return (selected_panel + 1) % len(names)
    if action == "previous_panel":
        return (selected_panel - 1) % len(names)
    if action == "detail":
        _show_panel_detail(stdscr, case_path, selected_panel)
        return selected_panel
    if action == "overview":
        Viewer(stdscr, overview_text(case_path)).display()
        return selected_panel
    return None


def _draw_cockpit(
    stdscr: Any,
    lines: list[str],
    start_line: int,
    visible: int,
    width: int,
) -> None:
    stdscr.erase()
    for row, line in enumerate(lines[start_line : start_line + visible - 1]):
        with suppress(curses.error):
            stdscr.addstr(row, 0, line[: max(1, width - 1)])
    draw_status_bar(
        stdscr,
        "Captains Deck: tab/l next | h prev | Enter detail | r refresh | m menu | o full | q quit",
    )
    stdscr.refresh()


def _scroll_start_line(
    action: str | None,
    start_line: int,
    *,
    line_count: int,
    visible: int,
) -> int:
    if action == "down":
        return min(start_line + 1, max(0, line_count - visible))
    if action == "up":
        return max(0, start_line - 1)
    if action == "top":
        return 0
    if action == "bottom":
        return max(0, line_count - visible)
    return start_line


def _key_action(key: int) -> str | None:
    keys = get_config().keys
    checks = (
        ("quit", key in (ord("q"), ord("Q")) or key_in(key, keys.get("quit", []))),
        ("menu", key in (ord("m"), ord("M"))),
        ("detail", key in (10, 13)),
        ("next_panel", key in (9, ord("l"), curses.KEY_RIGHT)),
        ("previous_panel", key in (ord("h"), curses.KEY_LEFT)),
        ("refresh", key in (ord("r"), ord("R"), curses.KEY_RESIZE)),
        ("overview", key in (ord("o"), ord("O"))),
        ("down", key in (ord("j"), curses.KEY_DOWN) or key_in(key, keys.get("down", []))),
        ("up", key in (ord("k"), curses.KEY_UP) or key_in(key, keys.get("up", []))),
        ("top", key_in(key, keys.get("top", []))),
        ("bottom", key_in(key, keys.get("bottom", []))),
    )
    for action, matched in checks:
        if matched:
            return action
    return None


def _show_panel_detail(stdscr: Any, case_path: Path, selected_panel: int) -> None:
    names = cockpit_panel_names()
    panel = names[selected_panel % len(names)]
    lines = [panel, "-" * len(panel), *cockpit_panel_detail_lines(case_path, panel)]
    Viewer(stdscr, "\n".join(lines)).display()
