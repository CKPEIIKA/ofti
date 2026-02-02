from __future__ import annotations

import curses
from contextlib import suppress
from typing import Any


def prompt_input(stdscr: Any, prompt: str) -> str | None:  # noqa: C901, PLR0912
    """
    Read a single-line input. Returns None when ESC is pressed.
    """
    try:
        height, width = stdscr.getmaxyx()
        start_y, start_x = stdscr.getyx()
    except curses.error:
        height, width = 0, 0
        start_y, start_x = 0, 0
    if height and start_y >= height - 1:
        start_y = max(0, height - 2)
        start_x = 0
        with suppress(curses.error):
            stdscr.move(start_y, start_x)
            stdscr.clrtoeol()
    prompt_text = prompt[: max(0, width - start_x - 1)]
    try:
        stdscr.addstr(start_y, start_x, prompt_text)
    except TypeError:
        with suppress(curses.error):
            stdscr.addstr(prompt_text)
    except curses.error:
        pass
    stdscr.refresh()
    try:
        start_y, start_x = stdscr.getyx()
    except curses.error:
        start_y, start_x = 0, 0
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
            with suppress(curses.error):
                height, width = stdscr.getmaxyx()
                stdscr.move(start_y, start_x)
                stdscr.clrtoeol()
                if start_y < height:
                    available = max(0, width - start_x - 1)
                    visible = "".join(buffer)
                    if available and len(visible) > available:
                        visible = visible[-available:]
                    stdscr.addstr(visible)
                    cursor_pos = min(start_x + cursor, max(0, width - 1))
                    stdscr.move(start_y, cursor_pos)
                    stdscr.refresh()
    finally:
        with suppress(curses.error):
            curses.curs_set(0)
