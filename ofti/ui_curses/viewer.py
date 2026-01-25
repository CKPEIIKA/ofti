from __future__ import annotations

import curses
from contextlib import suppress
from typing import Any

from ofti.foam.config import get_config, key_hint, key_in


class Viewer:
    def __init__(self, stdscr: Any, content: str) -> None:
        self.stdscr = stdscr
        self.content = content

    def display(self) -> None:  # noqa: C901, PLR0912
        lines = self.content.splitlines()
        start_line = 0
        search_term: str | None = None

        while True:
            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()
            back_hint = key_hint("back", "h")
            header = f"Press {back_hint} or Enter to exit, '?' for help."
            with suppress(curses.error):
                self.stdscr.addstr(header[: max(1, width - 1)] + "\n\n")
            end_line = start_line + height - 3

            for line in lines[start_line:end_line]:
                text = line[: max(1, width - 1)]
                try:
                    self.stdscr.addstr(text + "\n")
                except curses.error:
                    break

            self.stdscr.refresh()
            key = self.stdscr.getch()

            if key_in(key, get_config().keys.get("quit", [])):
                return
            if key == ord("?"):
                self._show_help()
                continue

            if key == curses.KEY_RESIZE:
                continue

            if key_in(key, get_config().keys.get("search", [])):
                curses.echo()
                self.stdscr.clear()
                self.stdscr.addstr("Search: ")
                self.stdscr.refresh()
                query = self.stdscr.getstr().decode()
                curses.noecho()
                if query:
                    search_term = query
                    start_index = end_line
                    found = None
                    for i in range(start_index, len(lines)):
                        if search_term in lines[i]:
                            found = i
                            break
                    if found is not None:
                        start_line = found
                    else:
                        for i in range(len(lines)):
                            if search_term in lines[i]:
                                start_line = i
                                break
                continue

            if key in (10, 13) or key_in(key, get_config().keys.get("back", [])):
                return
            if key_in(key, get_config().keys.get("top", [])):
                start_line = 0
            if key_in(key, get_config().keys.get("bottom", [])):
                start_line = max(0, len(lines) - (height - 3))
            if (
                key in (curses.KEY_DOWN,)
                or key_in(key, get_config().keys.get("down", []))
            ) and end_line < len(lines):
                start_line += 1
            if (
                key in (curses.KEY_UP,)
                or key_in(key, get_config().keys.get("up", []))
            ) and start_line > 0:
                start_line -= 1

    def _show_help(self) -> None:
        self.stdscr.clear()
        back_hint = key_hint("back", "h")
        self.stdscr.addstr("Viewer help\n\n")
        self.stdscr.addstr("  j / k or arrows : scroll\n")
        self.stdscr.addstr("  g / G           : top / bottom\n")
        self.stdscr.addstr(f"  {back_hint} or Enter  : exit viewer\n")
        self.stdscr.addstr("  /               : search within file\n")
        self.stdscr.addstr("  ?               : show this help\n\n")
        self.stdscr.addstr("Press any key to return.\n")
        self.stdscr.refresh()
        self.stdscr.getch()
