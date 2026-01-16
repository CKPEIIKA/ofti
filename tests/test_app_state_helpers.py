"""Helper-level tests for app state and command helpers."""

from __future__ import annotations

from pathlib import Path

import of_tui.app as app
import of_tui.commands as commands
from of_tui.openfoam import FileCheckResult


def test_command_suggestions_include_tools(monkeypatch) -> None:
    monkeypatch.setattr(commands, "list_tool_commands", lambda _path: ["blockMesh", "custom"])
    suggestions = commands.command_suggestions(Path("."))
    assert "tool blockMesh" in suggestions
    assert "run custom" in suggestions
    assert "blockMesh" in suggestions


def test_mode_status_includes_env(monkeypatch) -> None:
    state = app.AppState(no_foam=True)
    monkeypatch.setenv("WM_PROJECT_DIR", "/WM")
    text = app._mode_status(state)
    assert "no-foam" in text
    assert "/WM" in text


def test_check_status_line_when_running(monkeypatch) -> None:
    state = app.AppState(no_foam=False)
    with state.check_lock:
        state.check_in_progress = True
        state.check_done = 2
        state.check_total = 5
        state.check_current = Path("system/controlDict")
    line = state.check_status_line()
    assert "check:" in line
    assert "controlDict" in line


def test_check_labels_defaults_not_checked(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    files = [case_dir / "system" / "controlDict"]
    labels, checks = app._check_labels(case_dir, files, app.AppState())
    assert "Not checked" in labels[0]
    assert checks[0] is None


def test_check_labels_with_results(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    path = case_dir / "system" / "controlDict"
    result = FileCheckResult(errors=["bad"], warnings=[], checked=True)
    state = app.AppState()
    state.check_results = {path: result}
    labels, checks = app._check_labels(case_dir, [path], state)
    assert "ERROR" in labels[0]
    assert checks[0] == result


def test_menu_scroll_bounds(monkeypatch) -> None:
    class FakeScreen:
        def getmaxyx(self):
            return (10, 80)

    screen = FakeScreen()
    assert app._menu_scroll(0, 0, screen, 100, header_rows=3) == 0
    assert app._menu_scroll(50, 0, screen, 100, header_rows=3) > 0


def test_start_check_thread_updates_state(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    path = case_dir / "system" / "controlDict"
    path.write_text("application simpleFoam;")
    state = app.AppState()

    def fake_verify(_case, progress=None):
        if progress:
            progress(path)
        return {path: FileCheckResult(checked=True)}

    monkeypatch.setattr(app, "verify_case", fake_verify)
    monkeypatch.setattr(app, "discover_case_files", lambda _case: {"system": [path]})

    app._start_check_thread(case_dir, state)
    assert state.check_thread is not None
    state.check_thread.join(timeout=1.0)
    assert state.check_results is not None
    assert state.check_in_progress is False
