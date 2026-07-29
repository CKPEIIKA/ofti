from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ofti.app.commands import CommandCallbacks
from ofti.app.screens import check, editor
from ofti.app.state import AppState
from ofti.foam.config import Config
from ofti.foam.openfoam import FileCheckResult, OpenFOAMError
from ofti.ui_curses.entry_browser import BrowserCallbacks


class Screen:
    def __init__(self, keys: list[int] | None = None) -> None:
        self.keys = list(keys or [])
        self.lines: list[str] = []
        self.timeout_values: list[int] = []

    def clear(self) -> None:
        self.lines.clear()

    def addstr(self, *args: object) -> None:
        self.lines.append(str(args[-1]))

    def refresh(self) -> None:
        return None

    def getch(self) -> int:
        return self.keys.pop(0) if self.keys else ord("h")

    def getmaxyx(self) -> tuple[int, int]:
        return (12, 80)

    def timeout(self, value: int) -> None:
        self.timeout_values.append(value)

    def attron(self, *_args: object) -> None:
        return None

    def attroff(self, *_args: object) -> None:
        return None


def _case(tmp_path: Path) -> tuple[Path, Path]:
    case = tmp_path / "case"
    control = case / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    control.write_text("application simpleFoam;\n")
    (case / "constant").mkdir()
    (case / "0").mkdir()
    (case / "0" / "U").write_text("internalField uniform (0 0 0);\n")
    return case, control


def _callbacks() -> CommandCallbacks:
    return cast("CommandCallbacks", SimpleNamespace())


def _browser_callbacks() -> BrowserCallbacks:
    return cast("BrowserCallbacks", SimpleNamespace())


def test_editor_case_scan_filters_runtime_noise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    (case / "system" / ".hidden").write_text("x")
    (case / "system" / "backup~").write_text("x")
    (case / "system" / "folder").mkdir()
    (case / "0.orig").mkdir()
    (case / "0.orig" / "p").write_text("internalField uniform 0;\n")

    sections = editor.simple_case_sections(case)

    assert sections["system"] == [control]
    assert [path.name for path in editor.scan_zero_dirs(case)] == ["0", "0.orig"]
    assert set(sections) == {"system", "0", "0.orig"}
    monkeypatch.setattr(editor.os, "scandir", lambda _path: (_ for _ in ()).throw(OSError("denied")))
    assert editor.scan_dir_files(case) == []
    assert editor.scan_zero_dirs(case) == []


def test_editor_screen_opens_selected_file_then_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    state = AppState()
    selections = iter([control, None])
    opened: list[Path] = []
    monkeypatch.setattr(editor, "select_case_file", lambda *_a, **_k: next(selections))
    monkeypatch.setattr(editor, "entry_browser_screen", lambda _s, _c, path, *_a: opened.append(path))

    editor.editor_screen(
        Screen(),
        case,
        state,
        command_callbacks=_callbacks(),
        browser_callbacks=_browser_callbacks(),
    )

    assert opened == [control]
    assert state.current_screen.value == "editor"


def test_select_case_file_handles_empty_back_and_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    messages: list[str] = []
    monkeypatch.setattr(editor, "show_message", lambda _screen, message: messages.append(message))
    assert editor.select_case_file(Screen(), case, AppState(), {}, _callbacks()) is None
    assert messages == ["No OpenFOAM case files found in this case."]

    choices = iter([0, 0])

    class Menu:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def navigate(self) -> int:
            return next(choices)

    monkeypatch.setattr(editor, "Menu", Menu)
    state = AppState()
    selected = editor.select_case_file(Screen(), case, state, {"system": [control]}, _callbacks())
    assert selected == control
    assert state.last_section == "system"
    assert state.last_file == "system/controlDict"


def test_file_screens_dispatch_edit_view_and_external_editor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    calls: list[str] = []
    choices = iter([0, 1, -1])

    class Submenu:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def navigate(self) -> int:
            return next(choices)

    monkeypatch.setattr(editor, "Submenu", Submenu)
    monkeypatch.setattr(editor, "list_keywords", lambda _path: ["application"])
    monkeypatch.setattr(editor, "edit_entry_screen", lambda *_a, **_k: calls.append("edit"))
    monkeypatch.setattr(editor, "view_file_screen", lambda *_a, **_k: calls.append("view"))
    editor.file_screen(Screen(), case, control, AppState(), _callbacks())
    assert calls == ["edit", "view"]

    choices = iter([0, 1, -1])
    monkeypatch.setattr(editor, "Menu", Submenu)
    monkeypatch.setattr(editor, "open_file_in_editor", lambda *_a: calls.append("external"))
    editor.no_foam_file_screen(Screen(), case, control, AppState(), _callbacks())
    assert calls[-2:] == ["view", "external"]


def test_file_screen_and_view_report_read_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    screen = Screen([ord("x")])
    monkeypatch.setattr(editor, "list_keywords", lambda _path: (_ for _ in ()).throw(OpenFOAMError("bad")))
    editor.file_screen(screen, case, control, AppState(), _callbacks())
    assert any("Error reading" in line for line in screen.lines)

    messages: list[str] = []
    monkeypatch.setattr(editor, "show_message", lambda _screen, message: messages.append(message))
    editor.view_file_screen(screen, case / "missing")
    assert messages[-1].startswith("Failed to read file:")


def test_edit_entry_reads_validates_and_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    saved: list[tuple[list[str], str]] = []

    class Menu:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def navigate(self) -> int:
            return 0

    class EntryEditor:
        def __init__(self, _screen: object, _entry: object, on_save: Any, **_kwargs: object) -> None:
            self.on_save = on_save

        def edit(self) -> None:
            assert self.on_save("rhoSimpleFoam") is True

    monkeypatch.setattr(editor, "Menu", Menu)
    monkeypatch.setattr(editor, "list_subkeys", lambda *_a: [])
    monkeypatch.setattr(editor, "read_entry", lambda *_a: "simpleFoam")
    monkeypatch.setattr(editor, "choose_validator", lambda *_a: (None, "word"))
    monkeypatch.setattr(editor, "detect_type_with_foamlib", lambda _p, _k, validator, label: (validator, label))
    monkeypatch.setattr(editor, "EntryEditor", EntryEditor)
    monkeypatch.setattr(
        editor,
        "apply_assignment_or_write",
        lambda _case, _path, keys, value: saved.append((keys, value)) or True,
    )
    editor.edit_entry_screen(
        Screen(),
        case,
        control,
        ["application"],
        AppState(),
        command_callbacks=_callbacks(),
    )
    assert saved == [(["application"], "rhoSimpleFoam")]


def test_edit_entry_empty_nested_and_read_failure_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    messages: list[str] = []
    monkeypatch.setattr(editor, "show_message", lambda _screen, message: messages.append(message))
    editor.edit_entry_screen(Screen(), case, control, [], AppState(), command_callbacks=_callbacks())
    assert messages[-1] == "No entries found in file."

    choices = iter([0, 2])

    class Menu:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def navigate(self) -> int:
            return next(choices)

    monkeypatch.setattr(editor, "Menu", Menu)
    monkeypatch.setattr(editor, "list_subkeys", lambda *_a: ["p"])
    editor.edit_entry_screen(Screen(), case, control, ["solvers"], AppState(), command_callbacks=_callbacks())
    monkeypatch.setattr(editor, "list_subkeys", lambda *_a: [])
    monkeypatch.setattr(editor, "read_entry", lambda *_a: (_ for _ in ()).throw(OpenFOAMError("bad")))
    choices = iter([0])
    editor.edit_entry_screen(
        Screen(),
        case,
        control,
        ["application"],
        AppState(),
        command_callbacks=_callbacks(),
    )
    assert messages[-1] == "Failed to read entry: bad"


def test_file_annotation_view_and_external_editor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "dict"
    path.write_text("good\nbad\n")
    monkeypatch.setattr(editor, "find_suspicious_lines", lambda _text: ["Line 2: suspicious", "general"])
    annotated = editor._annotate_content(path.read_text(), ["extra"])
    assert "bad  // LINT: suspicious" in annotated
    assert "// LINT: general" in annotated
    assert "// LINT: extra" in annotated

    viewed: list[str] = []

    class Viewer:
        def __init__(self, _screen: object, content: str) -> None:
            viewed.append(content)

        def display(self) -> None:
            return None

    monkeypatch.setattr(editor, "Viewer", Viewer)
    editor.view_file_screen(Screen(), path, ["manual warning"])
    assert "manual warning" in viewed[-1]

    messages: list[str] = []
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr(editor, "show_message", lambda _screen, message: messages.append(message))
    editor.open_file_in_editor(Screen(), path)
    monkeypatch.setenv("EDITOR", "editor")
    monkeypatch.setattr(editor.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no")))
    editor.open_file_in_editor(Screen(), path)
    assert messages == ["EDITOR is not set.", "Failed to open editor: no"]


def _check_config() -> Config:
    cfg = Config()
    cfg.keys.update(
        {
            "up": ["k"],
            "down": ["j"],
            "top": ["g"],
            "bottom": ["G"],
            "back": ["h"],
            "help": ["?"],
            "command": [":"],
            "select": ["\n"],
            "view": ["v"],
        },
    )
    return cfg


def test_check_thread_records_success_and_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    state = AppState()

    def verify(_case: Path, *, progress: Any, result_callback: Any) -> dict[Path, FileCheckResult]:
        result = FileCheckResult(checked=True)
        progress(control)
        result_callback(control, result)
        return {control: result}

    def start(_name: str, worker: Any, *, message: str) -> Any:
        task = SimpleNamespace(cancel=threading.Event(), message=message, status="running", thread=None)
        worker(task)
        return task

    monkeypatch.setattr(check, "discover_case_files", lambda _case: {"system": [control]})
    monkeypatch.setattr(check, "verify_case", verify)
    monkeypatch.setattr(state.tasks, "start", start)
    check.start_check_thread(case, state)
    assert state.check_done == 1
    assert state.check_current == control
    assert state.check_results == {control: FileCheckResult(checked=True)}
    assert state.check_in_progress is False


def test_check_menu_handles_navigation_help_and_unchecked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    screen = Screen([ord("j"), ord("k"), ord("g"), ord("G"), ord("?"), 10, ord("h")])
    messages: list[str] = []
    monkeypatch.setattr(check, "get_config", _check_config)
    monkeypatch.setattr(check, "discover_case_files", lambda _case: {"system": [control]})
    monkeypatch.setattr(check, "draw_check_menu", lambda *_a, **_k: None)
    monkeypatch.setattr(check, "show_message", lambda _screen, message: messages.append(message))
    check.check_syntax_menu(screen, case, AppState(), command_callbacks=_callbacks())
    assert any("Check syntax menu" in message for message in messages)
    assert any("not checked yet" in message for message in messages)
    assert screen.timeout_values == [200, -1]


def test_check_menu_opens_checked_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    state = AppState(check_results={control: FileCheckResult(checked=True, warnings=["warn"])})
    viewed: list[tuple[Path, list[str] | None]] = []
    monkeypatch.setattr(check, "get_config", _check_config)
    monkeypatch.setattr(check, "discover_case_files", lambda _case: {"system": [control]})
    monkeypatch.setattr(check, "draw_check_menu", lambda *_a, **_k: None)
    monkeypatch.setattr(check, "show_check_result", lambda *_a: True)
    monkeypatch.setattr(
        check, "view_file_screen", lambda _s, path, lint_warnings=None: viewed.append((path, lint_warnings))
    )
    check.check_syntax_menu(Screen([10, ord("h")]), case, state, command_callbacks=_callbacks())
    assert viewed == [(control, ["warn"])]


@pytest.mark.parametrize(
    ("result", "key", "expected"),
    [
        (FileCheckResult(checked=False), ord("h"), False),
        (FileCheckResult(checked=True), ord("v"), True),
        (FileCheckResult(checked=True, errors=["bad"]), ord("f"), False),
    ],
)
def test_show_check_result_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: FileCheckResult,
    key: int,
    expected: bool,
) -> None:
    fixed: list[Path] = []
    monkeypatch.setattr(check, "get_config", _check_config)
    monkeypatch.setattr(check, "auto_fix_missing_required_entries", lambda _s, path, *_a: fixed.append(path))
    path = tmp_path / "dict"
    assert check.show_check_result(Screen([key]), path, Path("dict"), result) is expected
    assert bool(fixed) is (key == ord("f"))


def test_auto_fix_reports_missing_template_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case, control = _case(tmp_path)
    messages: list[str] = []
    monkeypatch.setattr(check, "show_message", lambda _screen, message: messages.append(message))
    check.auto_fix_missing_required_entries(Screen(), control, Path("system/controlDict"), FileCheckResult())
    assert messages[-1] == "No missing required entries detected."

    result = FileCheckResult(checked=True, errors=["solvers: missing required entries: p"])
    monkeypatch.setattr(check, "find_example_file", lambda _rel: None)
    check.auto_fix_missing_required_entries(Screen(), control, Path("system/controlDict"), result)
    assert messages[-1] == "No example template found to auto-fix this file."

    example = case / "example"
    example.write_text("x")
    monkeypatch.setattr(check, "find_example_file", lambda _rel: example)
    monkeypatch.setattr(check, "read_entry", lambda *_a: (_ for _ in ()).throw(OpenFOAMError("missing")))
    monkeypatch.setattr(check, "get_entry_comments", lambda *_a: ["/* pressure solver */"])
    check.auto_fix_missing_required_entries(Screen(), control, Path("system/controlDict"), result)
    assert "solvers.p: pressure solver" in messages[-1]


def test_draw_check_menu_and_format_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    screen = Screen()
    monkeypatch.setattr(check, "draw_status_bar", lambda _screen, status: _screen.lines.append(status))
    monkeypatch.setattr(check.curses, "color_pair", lambda value: value)
    rows = [
        None,
        FileCheckResult(checked=True),
        FileCheckResult(checked=True, warnings=["warn"]),
        FileCheckResult(checked=True, errors=["bad"]),
    ]
    check.draw_check_menu(
        screen,
        ["none", "ok", "warn", "bad"],
        rows,
        current=1,
        scroll=0,
        status="ready",
    )
    assert any(">> ok" in line for line in screen.lines)
    assert screen.lines[-1] == "ready"
    assert check._format_fix_item("p", None) == "- p"
    assert check._format_fix_item("p", "pressure") == "- p: pressure"
