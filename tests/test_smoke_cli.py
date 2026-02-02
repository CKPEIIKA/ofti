"""Smoke tests for starting the TUI in headless mode."""

from __future__ import annotations

from pathlib import Path

from ofti.app import app


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
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;")
    screen = FakeScreen(keys=[ord("q")])

    def fake_wrapper(func, *args, **kwargs):
        return func(screen, *args, **kwargs)

    monkeypatch.setattr(app.curses, "wrapper", fake_wrapper)
    monkeypatch.setattr(app.curses, "start_color", lambda: None)
    def fake_init_pair(*_args, **_kwargs):
        return None

    monkeypatch.setattr(app.curses, "init_pair", fake_init_pair)

    app.run_tui(str(case_dir), debug=False)


def test_main_menu_navigates_config_manager(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;")

    keys = [ord("j"), ord("j"), ord("j"), ord("j"), 10, ord("h")]
    screen = FakeScreen(keys=keys)

    from ofti.app.screens import main as main_screen
    from ofti.app.state import AppState, Screen

    monkeypatch.setattr(main_screen, "fzf_enabled", lambda: False)
    callbacks = app._command_callbacks()
    result = main_screen.main_menu_screen(
        screen,
        case_dir,
        AppState(no_foam=True),
        command_callbacks=callbacks,
        editor_screen=lambda *_args, **_kwargs: None,
        check_syntax_screen=lambda *_args, **_kwargs: None,
        global_search_screen=lambda *_args, **_kwargs: None,
    )
    assert result == Screen.MAIN_MENU


def test_select_case_directory_accepts_current(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;")

    screen = FakeScreen(keys=[10])
    monkeypatch.setattr(app.curses, "color_pair", lambda *_args: 0)
    selected = app.select_case_directory(screen, case_dir)
    assert selected == case_dir
