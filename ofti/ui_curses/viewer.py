from __future__ import annotations

import curses
from contextlib import suppress
from typing import Any

from ofti.foam.config import get_config, key_hint, key_in

_HEADER_ROWS = 2
_HSCROLL_STEP = 8


class Viewer:
    """Read-only pager: vertical and horizontal scroll, paging, and search.

    ``start_at_end`` opens at the tail, which is where logs and command output
    carry their verdict.
    """

    def __init__(self, stdscr: Any, content: str, *, start_at_end: bool = False) -> None:
        self.stdscr = stdscr
        self.content = content
        self.start_at_end = start_at_end

    def display(self) -> None:
        lines = self.content.splitlines()
        height, _width = self.stdscr.getmaxyx()
        start_line = _max_start(lines, height) if self.start_at_end else 0
        column = 0

        while True:
            self._draw(lines, start_line, column)
            height, _width = self.stdscr.getmaxyx()
            page = max(1, height - _HEADER_ROWS)
            key = self.stdscr.getch()

            if self._is_exit(key):
                return
            if key == ord("?"):
                self._show_help()
                continue
            if key == ord("/") or key_in(key, get_config().keys.get("search", [])):
                start_line = self._search(lines, start_line, page)
                continue
            start_line, column = _scrolled(key, lines, start_line, column, page)

    def _is_exit(self, key: int) -> bool:
        cfg = get_config()
        return (
            key in (ord("q"), ord("h"), 10, 13)
            or key_in(key, cfg.keys.get("quit", []))
            or key_in(key, cfg.keys.get("back", []))
        )

    def _draw(self, lines: list[str], start_line: int, column: int) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        body_rows = max(1, height - _HEADER_ROWS)
        end_line = min(len(lines), start_line + body_rows)
        back_hint = key_hint("back", "h")
        position = f"{start_line + 1 if lines else 0}-{end_line}/{len(lines)}"
        if column:
            position = f"{position} col {column + 1}"
        header = f"[{position}]  {back_hint}/Enter: exit  PgUp/PgDn  </>: scroll  /: search  ?: help"
        with suppress(curses.error):
            self.stdscr.addstr(0, 0, header[: max(1, width - 1)], curses.A_REVERSE)
        for row, line in enumerate(lines[start_line:end_line], start=_HEADER_ROWS):
            with suppress(curses.error):
                self.stdscr.addstr(row, 0, line[column : column + max(1, width - 1)])
        self.stdscr.refresh()

    def _search(self, lines: list[str], start_line: int, page: int) -> int:
        height, width = self.stdscr.getmaxyx()
        curses.echo()
        try:
            with suppress(curses.error):
                self.stdscr.addstr(height - 1, 0, " " * max(1, width - 1))
                self.stdscr.addstr(height - 1, 0, "Search: ")
            self.stdscr.refresh()
            query = self.stdscr.getstr().decode(errors="replace")
        finally:
            curses.noecho()
        if not query:
            return start_line
        # Search forward from the line after the top of the page, then wrap.
        order = [*range(start_line + 1, len(lines)), *range(start_line + 1)]
        for index in order:
            if query in lines[index]:
                return min(index, max(0, len(lines) - page))
        return start_line

    def _show_help(self) -> None:
        self.stdscr.clear()
        back_hint = key_hint("back", "h")
        self.stdscr.addstr("Viewer help\n\n")
        self.stdscr.addstr("  j / k or arrows      : scroll one line\n")
        self.stdscr.addstr("  PgDn / Space, PgUp / b : scroll one page\n")
        self.stdscr.addstr("  g / G, Home / End    : top / bottom\n")
        self.stdscr.addstr("  Left / Right, < / >  : scroll long lines sideways\n")
        self.stdscr.addstr(f"  {back_hint} or Enter        : exit viewer\n")
        self.stdscr.addstr("  /                    : search forward (wraps)\n")
        self.stdscr.addstr("  ?                    : show this help\n\n")
        self.stdscr.addstr("Press any key to return.\n")
        self.stdscr.refresh()
        self.stdscr.getch()


def _max_start(lines: list[str], height: int) -> int:
    return max(0, len(lines) - max(1, height - _HEADER_ROWS))


def _scrolled(key: int, lines: list[str], start_line: int, column: int, page: int) -> tuple[int, int]:
    keys = get_config().keys
    last = max(0, len(lines) - page)
    vertical = {
        "down": min(last, start_line + 1),
        "up": max(0, start_line - 1),
        "page_down": min(last, start_line + page),
        "page_up": max(0, start_line - page),
        "top": 0,
        "bottom": last,
    }
    action = _vertical_action(key, keys)
    if action is not None:
        return vertical[action], column
    if key in (curses.KEY_RIGHT, ord(">")):
        return start_line, column + _HSCROLL_STEP
    if key in (curses.KEY_LEFT, ord("<")):
        return start_line, max(0, column - _HSCROLL_STEP)
    return start_line, column


def _vertical_action(key: int, keys: dict[str, list[str]]) -> str | None:
    table = (
        ("down", (curses.KEY_DOWN,), keys.get("down", [])),
        ("up", (curses.KEY_UP,), keys.get("up", [])),
        ("page_down", (curses.KEY_NPAGE, ord(" ")), []),
        ("page_up", (curses.KEY_PPAGE, ord("b")), []),
        ("top", (curses.KEY_HOME,), keys.get("top", [])),
        ("bottom", (curses.KEY_END,), keys.get("bottom", [])),
    )
    for action, codes, labels in table:
        if key in codes or key_in(key, labels):
            return action
    return None
