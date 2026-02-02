"""Tests for small app helpers to improve coverage."""

from __future__ import annotations

from pathlib import Path

from ofti.app import app, helpers, tasks
from ofti.app.tasks import recent_task_summary, running_tasks_status
from ofti.core.case_meta import case_metadata_quick
from ofti.core.entries import autoformat_value
from ofti.core.syntax import find_suspicious_lines
from ofti.foam.tasks import Task
from ofti.ui_curses import entry_browser as browser


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
    warnings = find_suspicious_lines(content)
    assert not warnings


def test_running_tasks_status() -> None:
    state = app.AppState()
    task = Task(name="solver", status="running", message="simpleFoam")
    state.tasks._tasks["solver"] = task
    text = running_tasks_status(state) or ""
    assert "running: solver(simpleFoam)" in text


def test_recent_task_summary(monkeypatch) -> None:
    state = app.AppState()
    task = Task(name="solver", status="done", message="simpleFoam")
    task.finished_at = 10.0
    state.tasks._tasks["solver"] = task
    monkeypatch.setattr(tasks.time, "time", lambda: 12.0)
    text = recent_task_summary(state) or ""
    assert "last: solver done" in text


def test_case_meta_placeholder(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    meta = case_metadata_quick(case_dir)
    assert meta["solver"] == "unknown"


def test_list_example_cases_includes_tutorials(tmp_path: Path, monkeypatch) -> None:
    tutorials = tmp_path / "tutorials" / "incompressible" / "icoFoam"
    tutorials.mkdir(parents=True)
    (tutorials / "system").mkdir()
    (tutorials / "system" / "controlDict").write_text("")

    monkeypatch.setenv("WM_PROJECT_DIR", str(tmp_path))
    cases = helpers._list_example_cases()
    assert tutorials in cases
