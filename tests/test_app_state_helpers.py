"""Helper-level tests for app state and command helpers."""

from __future__ import annotations

from pathlib import Path

from ofti.app import commands
from ofti.app import status as app_status
from ofti.app.helpers import menu_scroll
from ofti.app.screens import check as check_screen
from ofti.app.state import AppState
from ofti.foam.openfoam import FileCheckResult


def test_command_suggestions_include_tools(monkeypatch) -> None:
    monkeypatch.setattr(commands, "list_tool_commands", lambda _path: ["blockMesh", "custom"])
    suggestions = commands.command_suggestions(Path())
    assert "tool blockMesh" in suggestions
    assert "run custom" in suggestions
    assert "blockMesh" in suggestions


def test_mode_status_includes_env(monkeypatch) -> None:
    state = AppState(no_foam=True)
    monkeypatch.setenv("WM_PROJECT_DIR", "/WM")
    text = app_status.mode_status(state)
    assert "OpenFOAM env not found" in text
    assert "/WM" in text


def test_check_status_line_when_running(monkeypatch) -> None:
    state = AppState(no_foam=False)
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
    labels, checks = check_screen.check_labels(case_dir, files, AppState())
    assert "Not checked" in labels[0]
    assert checks[0] is None


def test_check_labels_with_results(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    path = case_dir / "system" / "controlDict"
    result = FileCheckResult(errors=["bad"], warnings=[], checked=True)
    state = AppState()
    state.check_results = {path: result}
    labels, checks = check_screen.check_labels(case_dir, [path], state)
    assert "ERROR" in labels[0]
    assert checks[0] == result


def test_menu_scroll_bounds(monkeypatch) -> None:
    class FakeScreen:
        def getmaxyx(self):
            return (10, 80)

    screen = FakeScreen()
    assert menu_scroll(0, 0, screen, 100, header_rows=3) == 0
    assert menu_scroll(50, 0, screen, 100, header_rows=3) > 0


def test_start_check_thread_updates_state(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    path = case_dir / "system" / "controlDict"
    path.write_text("application simpleFoam;")
    state = AppState()

    def fake_verify(_case, progress=None, result_callback=None):
        if progress:
            progress(path)
        if result_callback:
            result_callback(path, FileCheckResult(checked=True))
        return {path: FileCheckResult(checked=True)}

    monkeypatch.setattr(check_screen, "verify_case", fake_verify)
    monkeypatch.setattr(check_screen, "discover_case_files", lambda _case: {"system": [path]})

    check_screen.start_check_thread(case_dir, state)
    task = state.tasks.get("check_syntax")
    assert task is not None
    assert task.status in {"running", "done"}
    assert state.check_thread is not None
    state.check_thread.join(timeout=1.0)
    assert state.check_results is not None
    assert state.check_in_progress is False
