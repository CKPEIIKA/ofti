"""Tests for small app helpers to improve coverage."""

from __future__ import annotations

from pathlib import Path

import of_tui.app as app
from of_tui import browser
from of_tui.editor import autoformat_value


def test_color_from_name_defaults() -> None:
    assert app._color_from_name("red", 0) >= 0
    assert app._color_from_name("unknown", 7) == 7


def test_entry_browser_scroll_bounds(monkeypatch) -> None:
    class FakeScreen:
        def getmaxyx(self):
            return (10, 80)

    screen = FakeScreen()
    assert browser._entry_browser_scroll(0, 0, screen, 100) == 0
    assert browser._entry_browser_scroll(50, 0, screen, 100) > 0


def test_autoformat_value_trims() -> None:
    assert autoformat_value(" 1 ") == "1"
    assert autoformat_value("line\n") == "line"


def test_next_significant_line_skips_block(tmp_path: Path) -> None:
    content = "\n".join(["simpleCoeffs", "{", "value 1;", "}"])
    warnings = app._find_suspicious_lines(content)
    assert not warnings
