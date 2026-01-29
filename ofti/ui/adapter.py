from __future__ import annotations

from typing import Any


class CursesAdapter:
    """Thin wrapper around curses stdscr to allow future UI swapping."""

    def __init__(self, stdscr: Any) -> None:
        self._stdscr = stdscr

    @property
    def stdscr(self) -> Any:
        return self._stdscr

    def clear(self) -> None:
        self._stdscr.clear()

    def refresh(self) -> None:
        self._stdscr.refresh()

    def addstr(self, *args: Any, **kwargs: Any) -> None:
        self._stdscr.addstr(*args, **kwargs)

    def getch(self) -> int:
        return self._stdscr.getch()

    def getmaxyx(self) -> tuple[int, int]:
        return self._stdscr.getmaxyx()
