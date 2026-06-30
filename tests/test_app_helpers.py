"""Tests for small app helpers to improve coverage."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

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


def test_case_flag_and_probable_case_detection(tmp_path: Path) -> None:
    definite = tmp_path / "definite"
    (definite / "system").mkdir(parents=True)
    (definite / "system" / "controlDict").write_text("application simpleFoam;\n")
    assert helpers.case_flag(definite) == "OF case"

    probable = tmp_path / "probable"
    (probable / "system").mkdir(parents=True)
    (probable / "constant").mkdir()
    assert helpers.case_flag(probable) == "probably OF case"

    plain = tmp_path / "plain"
    plain.mkdir()
    assert helpers.case_flag(plain) == ""


def test_case_chooser_entries_respect_search_and_flags(tmp_path: Path) -> None:
    case_dir = tmp_path / "caseA"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    probable_dir = tmp_path / "caseB"
    (probable_dir / "system").mkdir(parents=True)
    (probable_dir / "constant").mkdir()
    note = tmp_path / "notes.txt"
    note.write_text("x")

    entries = helpers._case_chooser_entries(
        tmp_path,
        dirs=[case_dir, probable_dir],
        files=[note],
        query="case",
    )
    labels = [label for label, _ in entries]

    assert any(label == "caseA/ [OF case]" for label in labels)
    assert any(label == "caseB/ [probably OF case]" for label in labels)
    assert "notes.txt" not in labels


def test_running_case_choices_dedupe_visible_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    other = tmp_path / "not-case"
    other.mkdir()

    rows = [
        {"case": str(case), "pid": 10, "solver": "simpleFoam"},
        {"case": str(case), "pid": 11, "solver": "simpleFoam"},
        {"case": str(other), "pid": 12, "solver": "pisoFoam"},
        {"case": "", "pid": 13, "solver": "unknown"},
    ]
    monkeypatch.setattr(helpers, "_scan_proc_solver_processes", lambda *_a, **_k: rows)

    choices = helpers.discover_running_case_choices(tmp_path)

    assert len(choices) == 1
    assert choices[0].path == case.resolve()
    assert choices[0].pids == (10, 11)
    assert choices[0].solvers == ("simpleFoam",)


def test_select_start_case_can_choose_running_or_browse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    browsed = tmp_path / "browsed"
    (browsed / "system").mkdir(parents=True)
    (browsed / "system" / "controlDict").write_text("application pisoFoam;\n")

    monkeypatch.setattr(
        helpers,
        "discover_running_case_choices",
        lambda _path: [helpers.RunningCaseChoice(case.resolve(), (101,), ("simpleFoam",))],
    )

    class _Menu:
        choices: ClassVar[list[int]] = [0]

        def __init__(self, *_args, **_kwargs) -> None:
            self.current_option = self.choices.pop(0)

        def display(self) -> None:
            return

    monkeypatch.setattr(helpers, "Menu", _Menu)

    class _Screen:
        def getch(self) -> int:
            return 10

    assert helpers.select_start_case(_Screen(), tmp_path) == case.resolve()

    _Menu.choices = [1]
    monkeypatch.setattr(helpers, "select_case_directory", lambda *_a, **_k: browsed)
    assert helpers.select_start_case(_Screen(), tmp_path) == browsed


def test_select_start_case_current_and_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    monkeypatch.setattr(helpers, "discover_running_case_choices", lambda _path: [])

    class _Menu:
        def __init__(self, *_args, **_kwargs) -> None:
            self.current_option = 0

        def display(self) -> None:
            return

    class _SelectScreen:
        def getch(self) -> int:
            return 10

    class _BackScreen:
        def getch(self) -> int:
            return ord("h")

    monkeypatch.setattr(helpers, "Menu", _Menu)
    assert helpers.select_start_case(_SelectScreen(), case) == case.resolve()
    assert helpers.select_start_case(_BackScreen(), case) is None


def test_running_case_choices_handles_scan_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_os_error(*_args, **_kwargs):
        raise OSError("proc not available")

    monkeypatch.setattr(helpers, "_scan_proc_solver_processes", _raise_os_error)
    assert helpers.discover_running_case_choices(tmp_path) == []


def test_start_case_labels_and_hints(tmp_path: Path) -> None:
    case = tmp_path / "case"
    choice = helpers.RunningCaseChoice(case, (1, 2), ("pisoFoam", "simpleFoam"))

    assert helpers._current_case_label(case).startswith("[Current case]")
    assert "pids=2" in helpers._running_case_label(choice)
    assert "directory" in helpers._start_case_hint("browse")
    assert "running" in helpers._start_case_hint("running")
    assert "current" in helpers._start_case_hint("current")
    assert "Exit" in helpers._start_case_hint("other")


def test_start_case_navigation_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Menu:
        def __init__(self, *_args, **_kwargs) -> None:
            self.current_option = 0

        def display(self) -> None:
            return

    class _Screen:
        def __init__(self, keys: list[int]) -> None:
            self.keys = keys

        def getch(self) -> int:
            return self.keys.pop(0)

    monkeypatch.setattr(helpers, "Menu", _Menu)

    choice = helpers._navigate_start_case_menu(
        _Screen([ord("j"), ord("j"), ord("k"), ord("g"), ord("G"), 10]),
        ["one", "two", "three"],
        ["running", "running", "browse"],
        extra_lines=[],
    )
    assert choice == 2

    with pytest.raises(helpers.QuitAppError):
        helpers._navigate_start_case_menu(
            _Screen([ord("q")]),
            ["one"],
            ["browse"],
            extra_lines=[],
        )


def test_list_dir_entries_skips_only_denied_entries(tmp_path: Path, monkeypatch) -> None:
    class FakeEntry:
        def __init__(self, name: str, *, kind: str, denied: bool = False) -> None:
            self.name = name
            self.path = str(tmp_path / name)
            self.kind = kind
            self.denied = denied

        def is_dir(self) -> bool:
            if self.denied:
                raise PermissionError("denied")
            return self.kind == "dir"

        def is_file(self) -> bool:
            if self.denied:
                raise PermissionError("denied")
            return self.kind == "file"

    monkeypatch.setattr(
        helpers.os,
        "scandir",
        lambda _path: [
            FakeEntry("case", kind="dir"),
            FakeEntry("crypta", kind="dir", denied=True),
            FakeEntry("README", kind="file"),
        ],
    )

    dirs, files = helpers.list_dir_entries(tmp_path)

    assert dirs == [tmp_path / "case"]
    assert files == [tmp_path / "README"]
