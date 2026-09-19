from __future__ import annotations

import curses
from pathlib import Path
from types import SimpleNamespace

import pytest

from ofti.core.entries import Entry
from ofti.foam.config import Config
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import OpenFOAMError
from ofti.ui_curses import entry_editor, snappy_toggle, thermo_wizard


class Screen:
    def __init__(self, keys: list[int] | None = None, *, width: int = 80) -> None:
        self.keys = list(keys or [])
        self.lines: list[str] = []
        self.width = width

    def clear(self) -> None:
        self.lines.clear()

    def erase(self) -> None:
        self.lines.clear()

    def addstr(self, *args: object) -> None:
        self.lines.append(str(args[-1]))

    def refresh(self) -> None:
        return None

    def getch(self) -> int:
        return self.keys.pop(0) if self.keys else 27

    def getmaxyx(self) -> tuple[int, int]:
        return (20, self.width)

    def move(self, *_args: object) -> None:
        return None

    def derwin(self, *_args: object) -> Screen:
        return self


def _config() -> Config:
    cfg = Config()
    cfg.keys["quit"] = ["Q"]
    return cfg


def test_snappy_toggle_missing_and_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(snappy_toggle, "_show_message", lambda _screen, message: messages.append(message))
    assert snappy_toggle.snappy_staged_screen(Screen(), case) is False
    assert messages == ["Missing system/snappyHexMeshDict."]
    assert snappy_toggle._toggle_label("snap", enabled=True) == "[x] snap"
    assert snappy_toggle._toggle_label("snap", enabled=False) == "[ ] snap"

    path = case / "dict"
    path.write_text("x")
    monkeypatch.setattr(snappy_toggle, "read_entry", lambda _path, _key: "yes")
    assert snappy_toggle._read_bool(path, "snap", default=False) is True
    monkeypatch.setattr(snappy_toggle, "read_entry", lambda *_a: (_ for _ in ()).throw(OpenFOAMError("bad")))
    assert snappy_toggle._read_bool(path, "snap", default=True) is True


def test_snappy_toggle_applies_selected_stages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "case" / "system" / "snappyHexMeshDict"
    path.parent.mkdir(parents=True)
    path.write_text("castellatedMesh true;\n")
    choices = iter([0, 1, 2, 3])
    captured: list[tuple[Path, list[tuple[Path, list[str], str]]]] = []

    class Menu:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def navigate(self) -> int:
            return next(choices)

    monkeypatch.setattr(snappy_toggle, "Menu", Menu)
    monkeypatch.setattr(snappy_toggle, "read_entry", lambda _path, key: key != "addLayers")
    monkeypatch.setattr(snappy_toggle, "apply_edit_plan", lambda case, edits: captured.append((case, edits)))
    assert snappy_toggle.snappy_staged_screen(Screen(), path.parent.parent) is True
    assert captured[0][0] == path.parent.parent
    assert [edit[2] for edit in captured[0][1]] == ["false", "false", "true"]


def test_snappy_message_uses_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    viewed: list[str] = []

    class Viewer:
        def __init__(self, _screen: object, content: str) -> None:
            viewed.append(content)

        def display(self) -> None:
            return None

    monkeypatch.setattr(snappy_toggle, "Viewer", Viewer)
    snappy_toggle._show_message(Screen(), "message")
    assert "message" in viewed[0]
    assert "Press" in viewed[0]


def test_thermo_helpers_read_write_and_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    path = case / "constant" / "thermophysicalProperties"
    path.parent.mkdir(parents=True)
    path.write_text("x")
    monkeypatch.setattr(thermo_wizard, "read_entry", lambda *_a: "hePsiThermo")
    assert thermo_wizard._read_value(path, "thermoType.type") == "hePsiThermo"
    monkeypatch.setattr(thermo_wizard, "read_entry", lambda *_a: (_ for _ in ()).throw(OpenFOAMError("bad")))
    assert thermo_wizard._read_value(path, "thermoType.type") == ""

    writes: list[tuple[Path, list[str], str]] = []
    monkeypatch.setattr(
        thermo_wizard,
        "apply_assignment_or_write",
        lambda root, _path, keys, value: writes.append((root, keys, value)) or True,
    )
    assert thermo_wizard._write_value(path, "thermoType.type", " heRhoThermo ") is True
    assert writes == [(case, ["thermoType", "type"], "heRhoThermo")]
    assert thermo_wizard._write_value(path, "thermoType.type", "") is False
    assert thermo_wizard._slot_validator("janaf 1 2") is not None
    assert thermo_wizard._slot_validator("janaf 1 2 3 4 5 6 7") is None
    assert thermo_wizard._template_hint("{\n perfectGas\n}") == "perfectGas"
    assert thermo_wizard._template_hint("{}") == "Template"
    assert len(thermo_wizard._wizard_help_lines()) == 3


def test_thermo_wizard_reports_missing_manual_and_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    choices = iter([0, 0, 0, 1, 4])

    class Menu:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def navigate(self) -> int:
            return next(choices)

    monkeypatch.setattr(thermo_wizard, "Menu", Menu)
    monkeypatch.setattr(thermo_wizard, "_show_message", lambda _screen, message: messages.append(message))
    thermo_wizard.thermophysical_wizard_screen(Screen(), case)
    assert any("use Config Manager" in message for message in messages)
    assert any("template cannot be applied" in message for message in messages)


def test_thermo_wizard_manual_edit_and_template_outcomes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    path = case / "constant" / "thermophysicalProperties"
    path.parent.mkdir(parents=True)
    path.write_text("x")
    choices = iter([0, 0, 1, 1, 1, 1, 4])
    messages: list[str] = []
    writes = iter([True, False])

    class Menu:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def navigate(self) -> int:
            return next(choices)

    class Editor:
        def __init__(self, _screen: object, entry: Entry, **_kwargs: object) -> None:
            self.entry = entry

        def edit(self) -> None:
            self.entry.value = "manualType"

    monkeypatch.setattr(thermo_wizard, "Menu", Menu)
    monkeypatch.setattr(thermo_wizard, "EntryEditor", Editor)
    monkeypatch.setattr(thermo_wizard, "_read_value", lambda *_a: "old")
    monkeypatch.setattr(thermo_wizard, "_write_value", lambda *_a: next(writes))
    monkeypatch.setattr(thermo_wizard, "_show_message", lambda _screen, message: messages.append(message))
    thermo_wizard.thermophysical_wizard_screen(Screen(), case)
    assert messages == ["Applied mixture template.", "Failed to apply mixture template."]


def test_thermo_show_message_quit(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config()
    cfg.keys["quit"] = ["q"]
    monkeypatch.setattr(thermo_wizard, "get_config", lambda: cfg)
    with pytest.raises(QuitAppError):
        thermo_wizard._show_message(Screen([ord("q")]), "message")


def test_entry_editor_keyboard_editing_and_failed_save(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config()
    cfg.validate_on_save = False
    monkeypatch.setattr(entry_editor, "get_config", lambda: cfg)
    attempts: list[str] = []
    screen = Screen([curses.KEY_LEFT, ord("X"), curses.KEY_RIGHT, 127, curses.KEY_RESIZE, 10, ord("x"), 27])
    editor = entry_editor.EntryEditor(screen, Entry("key", "ab"), lambda value: attempts.append(value) or False)
    editor.edit()
    assert attempts == ["aX"]
    assert editor.entry.value == "ab"


def test_entry_editor_rejects_invalid_then_saves_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config()
    cfg.validate_on_save = True
    monkeypatch.setattr(entry_editor, "get_config", lambda: cfg)
    saved: list[str] = []
    screen = Screen([10, ord("n"), 10, ord("y"), ord("x")])
    editor = entry_editor.EntryEditor(
        screen,
        Entry("enabled", "false"),
        lambda value: saved.append(value) or True,
        validator=lambda _value: "warning",
        type_label="bool",
    )
    editor._buffer = "yes"
    editor.edit()
    assert saved == ["yes"]
    assert editor.entry.value == "yes"


def test_entry_editor_help_and_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs: list[str] = []

    class Viewer:
        def __init__(self, _screen: object, content: str) -> None:
            outputs.append(content)

        def display(self) -> None:
            return None

    monkeypatch.setattr(entry_editor, "Viewer", Viewer)
    monkeypatch.setattr(entry_editor, "resolve_executable", lambda _name: "/bin/foamHelp")
    monkeypatch.setattr(
        entry_editor,
        "run_trusted",
        lambda *_a, **_k: SimpleNamespace(stdout="help output", stderr=""),
    )
    editor = entry_editor.EntryEditor(Screen([ord("x"), ord("x"), ord("x")]), Entry("a.b", "1"), lambda _v: True)
    editor._foam_help()
    editor._check_value()
    editor.validator = lambda _value: "bad"
    editor._check_value()
    editor.validator = lambda _value: None
    editor._check_value()
    assert outputs == ["help output"]
    assert entry_editor._entry_editor_header("case") == "=== OFTI (case) ==="


def test_entry_editor_help_error_and_message_quit(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config()
    cfg.keys["quit"] = ["q"]
    monkeypatch.setattr(entry_editor, "get_config", lambda: cfg)
    editor = entry_editor.EntryEditor(Screen([ord("x")]), Entry("key", "1"), lambda _v: True)
    monkeypatch.setattr(entry_editor, "resolve_executable", lambda _name: (_ for _ in ()).throw(OSError("missing")))
    editor._foam_help()
    editor.stdscr = Screen([ord("q")])
    with pytest.raises(QuitAppError):
        editor._show_message("stop")
