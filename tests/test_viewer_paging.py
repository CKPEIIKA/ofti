from __future__ import annotations

import curses

import pytest

from ofti.foam.config import Config
from ofti.ui_curses import viewer as viewer_module
from ofti.ui_curses.viewer import Viewer


class _Screen:
    def __init__(self, keys: list[int], height: int = 12, width: int = 30) -> None:
        self._keys = list(keys)
        self.height = height
        self.width = width
        self.frames: list[dict[int, str]] = []
        self._rows: dict[int, str] = {}

    def getmaxyx(self) -> tuple[int, int]:
        return (self.height, self.width)

    def erase(self) -> None:
        self._rows = {}

    def clear(self) -> None:
        self._rows = {}

    def addstr(self, *args: object) -> None:
        if len(args) >= 3 and isinstance(args[0], int):
            self._rows[int(args[0])] = str(args[2])

    def refresh(self) -> None:
        self.frames.append(dict(self._rows))

    def getch(self) -> int:
        return self._keys.pop(0) if self._keys else ord("q")


class _SearchScreen(_Screen):
    def getstr(self) -> bytes:
        return b"needle"


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(viewer_module, "get_config", Config)


def _body(frame: dict[int, str]) -> list[str]:
    return [frame[row] for row in sorted(frame) if row >= 2]


def test_viewer_pages_and_reports_position() -> None:
    lines = [f"line {i}" for i in range(50)]
    screen = _Screen([curses.KEY_NPAGE, ord(" "), curses.KEY_PPAGE, curses.KEY_END])

    Viewer(screen, "\n".join(lines)).display()

    first, page_down, space, page_up, end = screen.frames[:5]
    assert _body(first)[0] == "line 0"
    assert "[1-10/50]" in first[0]
    assert _body(page_down)[0] == "line 10"
    assert _body(space)[0] == "line 20"
    assert _body(page_up)[0] == "line 10"
    assert _body(end)[-1] == "line 49"


def test_viewer_scrolls_long_lines_sideways_and_can_start_at_end() -> None:
    text = "\n".join(["x" * 8 + "tail-of-a-long-log-line-that-overflows", "last"])
    screen = _Screen([curses.KEY_RIGHT, curses.KEY_LEFT], height=3)

    Viewer(screen, text, start_at_end=True).display()

    start, right, left = screen.frames[:3]
    assert _body(start) == ["last"]
    assert "col 9" in right[0]
    assert "col" not in left[0]


def test_viewer_search_wraps_to_earlier_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(viewer_module.curses, "echo", lambda: None)
    monkeypatch.setattr(viewer_module.curses, "noecho", lambda: None)
    lines = ["needle", *[f"line {i}" for i in range(30)]]
    screen = _SearchScreen([curses.KEY_END, ord("/")])

    Viewer(screen, "\n".join(lines)).display()

    assert _body(screen.frames[-1])[0] == "needle"
