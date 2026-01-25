"""Tests for small app helpers to improve coverage."""

from __future__ import annotations

from pathlib import Path

from ofti.app import app
from ofti.core.entries import autoformat_value
from ofti.core.syntax import find_suspicious_lines
from ofti.ui_curses import entry_browser as browser


def test_color_from_name_defaults() -> None:
    assert app._color_from_name("red", 0) >= 0
    assert app._color_from_name("unknown", 7) == 7


def test_entry_browser_scroll_bounds(monkeypatch) -> None:  # noqa: ARG001
    class FakeScreen:
        def getmaxyx(self):
            return (10, 80)

    screen = FakeScreen()
    assert browser._entry_browser_scroll(0, 0, screen, 100) == 0
    assert browser._entry_browser_scroll(50, 0, screen, 100) > 0


def test_autoformat_value_trims() -> None:
    assert autoformat_value(" 1 ") == "1"
    assert autoformat_value("line\n") == "line"


def test_next_significant_line_skips_block(tmp_path: Path) -> None:  # noqa: ARG001
    content = "\n".join(["simpleCoeffs", "{", "value 1;", "}"])
    warnings = find_suspicious_lines(content)
    assert not warnings
