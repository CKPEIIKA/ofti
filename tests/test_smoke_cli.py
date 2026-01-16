"""Smoke tests for starting the TUI in headless mode."""

from __future__ import annotations

from pathlib import Path

import of_tui.app as app


class FakeScreen:
    def __init__(self, keys=None) -> None:
        self._keys = list(keys or [])
        self.height = 24
        self.width = 80

    def clear(self) -> None:
        pass

    def addstr(self, *args) -> None:
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("q")

    def getmaxyx(self):
        return (self.height, self.width)

    def move(self, *_args) -> None:
        pass

    def clrtoeol(self) -> None:
        pass

    def attron(self, *_args, **_kwargs) -> None:
        pass

    def attroff(self, *_args, **_kwargs) -> None:
        pass

    def derwin(self, *_args, **_kwargs):
        return self

    def erase(self) -> None:
        pass


def test_no_foam_smoke_runs_without_terminal(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("q")])

    def fake_wrapper(func, *args, **kwargs):
        return func(screen, *args, **kwargs)

    monkeypatch.setattr(app.curses, "wrapper", fake_wrapper)
    monkeypatch.setattr(app.curses, "start_color", lambda: None)
    monkeypatch.setattr(app.curses, "init_pair", lambda *args, **kwargs: None)

    app.run_tui(str(case_dir), debug=False, no_foam=True)
