from __future__ import annotations

import curses
from contextlib import suppress
from typing import Any


def prompt_input(stdscr: Any, prompt: str) -> str | None:
    """
    Read a single-line input. Returns None when ESC is pressed.
    """
    stdscr.addstr(prompt)
    stdscr.refresh()
    start_y, start_x = stdscr.getyx()
    buffer: list[str] = []
    cursor = 0

    with suppress(curses.error):
        curses.curs_set(1)
    try:
        while True:
            key = stdscr.getch()
            if key == 27:  # ESC
                return None
            if key in (curses.KEY_ENTER, 10, 13):
                return "".join(buffer).strip()
            if key in (curses.KEY_BACKSPACE, 127, 8):
                if cursor > 0:
                    buffer.pop(cursor - 1)
                    cursor -= 1
            elif key == curses.KEY_LEFT:
                if cursor > 0:
                    cursor -= 1
            elif key == curses.KEY_RIGHT:
                if cursor < len(buffer):
                    cursor += 1
            elif 32 <= key <= 126:
                buffer.insert(cursor, chr(key))
                cursor += 1
            stdscr.move(start_y, start_x)
            stdscr.clrtoeol()
            stdscr.addstr("".join(buffer))
            stdscr.move(start_y, start_x + cursor)
            stdscr.refresh()
    finally:
        with suppress(curses.error):
            curses.curs_set(0)
