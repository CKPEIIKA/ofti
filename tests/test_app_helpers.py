"""Tests for small app helpers to improve coverage."""

from __future__ import annotations

from pathlib import Path

from ofti.app import app
from ofti.core.entries import autoformat_value
from ofti.core.syntax import find_suspicious_lines
from ofti.foam.tasks import Task
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


def test_load_mpi_command(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    system_dir = case_dir / "system"
    system_dir.mkdir(parents=True)
    (system_dir / "mpi.conf").write_text("mpirun -np 8")
    assert app._load_mpi_command(case_dir) == ["mpirun", "-np", "8"]


def test_default_mpi_command(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    system_dir = case_dir / "system"
    system_dir.mkdir(parents=True)
    (system_dir / "decomposeParDict").write_text("")
    for idx in range(4):
        (case_dir / f"processor{idx}").mkdir()

    monkeypatch.setattr(app, "read_number_of_subdomains", lambda _path: 4)
    monkeypatch.setattr(app.shutil, "which", lambda _name: "/usr/bin/mpirun")

    assert app._default_mpi_command(case_dir) == ["mpirun", "-np", "4"]


def test_default_mpi_command_requires_processors(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    system_dir = case_dir / "system"
    system_dir.mkdir(parents=True)
    (system_dir / "decomposeParDict").write_text("")
    monkeypatch.setattr(app, "read_number_of_subdomains", lambda _path: 4)
    monkeypatch.setattr(app.shutil, "which", lambda _name: "/usr/bin/mpirun")

    assert app._default_mpi_command(case_dir) is None


def test_running_tasks_status() -> None:
    state = app.AppState()
    task = Task(name="solver", status="running", message="simpleFoam")
    state.tasks._tasks["solver"] = task
    text = app._running_tasks_status(state) or ""
    assert "running: solver(simpleFoam)" in text


def test_recent_task_summary(monkeypatch) -> None:
    state = app.AppState()
    task = Task(name="solver", status="done", message="simpleFoam")
    task.finished_at = 10.0
    state.tasks._tasks["solver"] = task
    monkeypatch.setattr(app.time, "time", lambda: 12.0)
    text = app._recent_task_summary(state) or ""
    assert "last: solver done" in text


def test_case_meta_placeholder(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    meta = app._case_meta_placeholder(case_dir)
    assert meta["solver"] == "unknown"
