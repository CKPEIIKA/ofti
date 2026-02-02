from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ofti.ui_curses.help import menu_hint
from ofti.ui_curses.menus import Menu


def build_menu(
    stdscr: Any,
    title: str,
    options: list[str],
    *,
    menu_key: str,
    item_hint: str | None = None,
    command_handler: Callable[[str], str | None] | None = None,
    command_suggestions: Callable[[], list[str]] | None = None,
    hint_provider: Callable[[int], str] | None = None,
    status_line: str | None = None,
    disabled_indices: set[int] | None = None,
    help_lines: list[str] | None = None,
) -> Menu:
    if hint_provider is None:
        def hint(idx: int) -> str:
            if not (0 <= idx < len(options)):
                return ""
            label = options[idx]
            if item_hint and label.lower() != "back":
                return item_hint
            return menu_hint(menu_key, label)

        hint_provider = hint

    return Menu(
        stdscr,
        title,
        options,
        hint_provider=hint_provider,
        command_handler=command_handler,
        command_suggestions=command_suggestions,
        status_line=status_line,
        disabled_indices=disabled_indices,
        help_lines=help_lines,
    )
