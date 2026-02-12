from __future__ import annotations

import curses
from typing import Any

from ofti.core.spinner import next_spinner


def draw_status_bar(stdscr: Any, text: str) -> None:
    try:
        height, width = stdscr.getmaxyx()
        stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(
            height - 1,
            0,
            text[: max(1, width - 1)].ljust(max(1, width - 1)),
        )
        stdscr.attroff(curses.A_REVERSE)
    except curses.error:
        pass


def status_message(stdscr: Any, message: str) -> None:
    try:
        height, width = stdscr.getmaxyx()
        spinner = next_spinner()
        stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(
            height - 1,
            0,
            f"{spinner} {message}"[: max(1, width - 1)].ljust(max(1, width - 1)),
        )
        stdscr.attroff(curses.A_REVERSE)
        stdscr.refresh()
    except curses.error:
        pass
