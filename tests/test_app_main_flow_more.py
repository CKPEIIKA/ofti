from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ofti.app import app
from ofti.app.state import AppState, Screen
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import OpenFOAMError
from ofti.foam.tasks import Task


class _Screen:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.timeout_value = -1

    def addstr(self, text: str) -> None:
        self.lines.append(text)

    def refresh(self) -> None:
        return

    def clear(self) -> None:
        self.lines.clear()

    def getch(self) -> int:
        return ord("h")

    def timeout(self, value: int) -> None:
        self.timeout_value = value


def _patch_curses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.curses, "start_color", lambda: None)
    monkeypatch.setattr(app.curses, "init_pair", lambda *_a, **_k: None)
    monkeypatch.setattr(app.curses, "COLOR_BLACK", 0, raising=False)
    monkeypatch.setattr(app.curses, "COLOR_CYAN", 1, raising=False)
    monkeypatch.setattr(app.curses, "COLOR_GREEN", 2, raising=False)
    monkeypatch.setattr(app.curses, "COLOR_YELLOW", 3, raising=False)
    monkeypatch.setattr(app.curses, "COLOR_RED", 4, raising=False)


def test_main_exits_when_case_not_selected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_curses(monkeypatch)
    state = AppState()
    called: list[str] = []

    monkeypatch.setattr(app, "get_config", lambda: SimpleNamespace(colors={}))
    monkeypatch.setattr(app, "is_case_dir", lambda _path: False)
    monkeypatch.setattr(app, "select_case_directory", lambda *_a, **_k: None)
    monkeypatch.setattr(app, "_main_loop", lambda *_a, **_k: called.append("loop"))

    app._main(_Screen(), tmp_path, False, state)

    assert called == []


def test_main_sets_no_foam_mode_and_runs_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_curses(monkeypatch)
    state = AppState()
    called: list[str] = []

    monkeypatch.setattr(app, "get_config", lambda: SimpleNamespace(colors={}))
    monkeypatch.setattr(app, "is_case_dir", lambda _path: True)
    monkeypatch.setattr(app, "ensure_environment", lambda: (_ for _ in ()).throw(OpenFOAMError("no env")))
    monkeypatch.setattr(app, "_main_loop", lambda *_a, **_k: called.append("loop"))

    app._main(_Screen(), tmp_path, False, state)

    assert called == ["loop"]
    assert state.no_foam is True


def test_main_handles_errors_by_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_curses(monkeypatch)
    state = AppState()
    messages: list[str] = []

    monkeypatch.setattr(app, "get_config", lambda: SimpleNamespace(colors={}))
    monkeypatch.setattr(app, "is_case_dir", lambda _path: True)
    monkeypatch.setattr(app, "ensure_environment", lambda: None)
    monkeypatch.setattr(app, "show_message", lambda _s, text: messages.append(text))

    monkeypatch.setattr(app, "_main_loop", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("boom")))
    app._main(_Screen(), tmp_path, False, state)
    assert "Unexpected error" in messages[-1]

    with pytest.raises(ValueError):
        app._main(_Screen(), tmp_path, True, state)

    monkeypatch.setattr(app, "_main_loop", lambda *_a, **_k: (_ for _ in ()).throw(QuitAppError()))
    app._main(_Screen(), tmp_path, False, state)


def test_main_loop_handles_empty_and_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    state = AppState()
    dispatch_calls: list[Screen] = []

    monkeypatch.setattr(app, "discover_case_files", lambda _path: {"system": []})
    app._main_loop(screen, case, state)
    assert any("No OpenFOAM case files found" in line for line in screen.lines)

    monkeypatch.setattr(app, "discover_case_files", lambda _path: {"system": [case / "system" / "controlDict"]})
    monkeypatch.setattr(app, "CursesAdapter", lambda stdscr: SimpleNamespace(stdscr=stdscr))

    class _Router:
        def __init__(self, handlers: dict[Screen, Any]) -> None:
            assert Screen.MAIN_MENU in handlers

        def dispatch(self, current: Screen, *_a, **_k) -> Screen | None:
            dispatch_calls.append(current)
            return None

    monkeypatch.setattr(app, "ScreenRouter", _Router)
    app._main_loop(_Screen(), case, state)
    assert dispatch_calls == [Screen.MAIN_MENU]


def test_tasks_and_terminal_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    messages: list[str] = []
    commands: list[list[str]] = []

    monkeypatch.setattr(app, "show_message", lambda _s, text: messages.append(text))
    app._tasks_screen(screen, AppState())
    assert "No background tasks running." in messages[-1]

    state = AppState()
    state.tasks._tasks["solver"] = Task(name="solver", status="running", message="ok")
    monkeypatch.setattr(app.Viewer, "display", lambda self: messages.append(self.content))
    app._tasks_screen(screen, state)
    assert "Background tasks:" in messages[-1]

    monkeypatch.setattr(app.curses, "def_prog_mode", lambda: None)
    monkeypatch.setattr(app.curses, "endwin", lambda: None)
    monkeypatch.setattr(app.curses, "reset_prog_mode", lambda: None)
    monkeypatch.setattr(app.subprocess, "run", lambda cmd, **_k: commands.append(list(cmd)))
    app._run_terminal(screen, case, "echo 1")
    assert commands[-1][:3] == ["bash", "--noprofile", "--norc"]

    monkeypatch.setenv("SHELL", "/bin/zsh")
    app._run_terminal(screen, case, None)
    assert commands[-1] == ["/bin/zsh"]

    monkeypatch.setattr(
        app.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    app._run_terminal(screen, case, "echo 2")


def test_command_and_browser_callbacks_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    called: list[str] = []
    state = AppState()

    monkeypatch.setattr(app, "command_suggestions", lambda _path: ["x"])
    monkeypatch.setattr(app, "handle_command", lambda *_a, **_k: called.append("command"))
    monkeypatch.setattr(app.check_screen, "check_syntax_screen", lambda *_a, **_k: called.append("check"))
    monkeypatch.setattr(app.editor_screen, "editor_screen", lambda *_a, **_k: called.append("editor"))
    monkeypatch.setattr(app.search_screen, "global_search_screen", lambda *_a, **_k: called.append("search"))
    monkeypatch.setattr(app, "mesh_menu", lambda *_a, **_k: called.append("mesh"))
    monkeypatch.setattr(app, "physics_menu", lambda *_a, **_k: called.append("physics"))
    monkeypatch.setattr(app, "simulation_menu", lambda *_a, **_k: called.append("sim"))
    monkeypatch.setattr(app, "postprocessing_menu", lambda *_a, **_k: called.append("post"))
    monkeypatch.setattr(app, "clean_case_menu", lambda *_a, **_k: called.append("clean"))
    monkeypatch.setattr(app, "diagnostics_screen", lambda *_a, **_k: called.append("diag"))
    monkeypatch.setattr(app, "config_menu", lambda *_a, **_k: called.append("config"))
    monkeypatch.setattr(app, "fzf_enabled", lambda: True)
    monkeypatch.setattr(app.editor_screen, "view_file_screen", lambda *_a, **_k: called.append("view"))

    callbacks = app._command_callbacks()
    callbacks.check_syntax(object(), case, state)
    callbacks.tools_screen(object(), case, state)
    callbacks.diagnostics_screen(object(), case, state)
    callbacks.mesh_menu(object(), case, state)
    callbacks.physics_menu(object(), case, state)
    callbacks.simulation_menu(object(), case, state)
    callbacks.postprocessing_menu(object(), case, state)
    callbacks.clean_menu(object(), case, state)
    callbacks.config_menu(object(), case, state)

    browser = app._browser_callbacks()
    screen = _Screen()
    browser.show_message(screen, "ok")
    browser.view_file(screen, case)
    browser.handle_command(screen, case, state, ":check")

    assert {"check", "diag", "mesh", "physics", "sim", "post", "clean", "config"} <= set(called)
    assert called.count("sim") >= 2
