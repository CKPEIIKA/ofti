from __future__ import annotations

import curses
from pathlib import Path
from types import SimpleNamespace

import pytest

from ofti.foam.config import Config
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import OpenFOAMError
from ofti.ui_curses import blockmesh_helper, high_speed, initial_conditions, inputs, layout, prompts, tool_dicts_ui
from ofti.ui_curses import help as help_ui
from ofti.ui_curses.viewer import Viewer


class Screen:
    def __init__(self, keys: list[int] | None = None, *, query: str = "needle", width: int = 48) -> None:
        self.keys = list(keys or [])
        self.lines: list[str] = []
        self.query = query
        self.width = width
        self.cursor = (0, 0)

    def clear(self) -> None:
        self.lines.clear()

    def erase(self) -> None:
        self.lines.clear()

    def addstr(self, *args: object) -> None:
        text = next((arg for arg in reversed(args) if isinstance(arg, str)), args[-1])
        self.lines.append(str(text))

    def refresh(self) -> None:
        return None

    def getch(self) -> int:
        return self.keys.pop(0) if self.keys else ord("h")

    def getstr(self) -> bytes:
        return self.query.encode()

    def getmaxyx(self) -> tuple[int, int]:
        return (8, self.width)

    def getyx(self) -> tuple[int, int]:
        return self.cursor

    def move(self, y: int, x: int) -> None:
        self.cursor = (y, x)

    def clrtoeol(self) -> None:
        return None

    def attron(self, *_args: object) -> None:
        return None

    def attroff(self, *_args: object) -> None:
        return None


def _config() -> Config:
    cfg = Config()
    cfg.keys.update(
        {
            "quit": ["Q"],
            "back": ["h"],
            "search": ["/"],
            "top": ["g"],
            "bottom": ["G"],
            "up": ["k"],
            "down": ["j"],
            "help": ["?"],
            "select": ["\n"],
        },
    )
    return cfg


def test_prompt_input_edits_cursor_and_cancels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inputs.curses, "curs_set", lambda _value: None)
    screen = Screen([ord("a"), ord("b"), curses.KEY_LEFT, ord("X"), curses.KEY_RIGHT, 127, 10])
    assert inputs.prompt_input(screen, "Value: ") == "aX"
    assert inputs.prompt_input(Screen([27]), "Value: ") is None


def test_prompt_command_parsing_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    values = iter([" a --flag ", "", "'broken", ""])
    messages: list[str] = []
    monkeypatch.setattr(prompts, "prompt_input", lambda *_a: next(values))
    monkeypatch.setattr(prompts, "_show_message", lambda _screen, message: messages.append(message))
    assert prompts.prompt_args_line(Screen(), "> ") == ["a", "--flag"]
    assert prompts.prompt_args_line(Screen(), "> ") == []
    assert prompts.prompt_args_line(Screen(), "> ") is None
    assert prompts.prompt_command_line(Screen(), "> ") is None
    assert messages[0].startswith("Invalid arguments:")
    assert messages[1] == "No command provided."


def test_prompt_message_can_quit(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config()
    cfg.keys["quit"] = ["q"]
    monkeypatch.setattr(prompts, "get_config", lambda: cfg)
    with pytest.raises(QuitAppError):
        prompts._show_message(Screen([ord("q")]), "message")


def test_layout_banner_and_status_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    screen = Screen(width=100)
    monkeypatch.setattr(layout.curses, "A_REVERSE", 1)
    layout.draw_status_bar(screen, "ready")
    layout.status_message(screen, "working")
    assert any("ready" in line for line in screen.lines)
    assert any("working" in line for line in screen.lines)
    meta = {
        "case_name": "cavity",
        "solver": "icoFoam",
        "status": "running",
        "latest_time": "1",
        "mesh": "OK",
        "parallel": "serial",
        "foam_version": "v2512",
        "case_header_version": "2312",
        "case_path": "/case",
        "running": "yes",
    }
    banner = layout.case_banner_lines(meta)
    assert banner[0].startswith("/*-")
    assert any("Running:" in line for line in banner)
    assert layout.case_overview_lines(meta) == []


def test_viewer_navigation_help_search_and_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config()
    monkeypatch.setattr("ofti.ui_curses.viewer.get_config", lambda: cfg)
    monkeypatch.setattr("ofti.ui_curses.viewer.curses.echo", lambda: None)
    monkeypatch.setattr("ofti.ui_curses.viewer.curses.noecho", lambda: None)
    screen = Screen([ord("?"), ord("x"), curses.KEY_RESIZE, ord("G"), ord("g"), ord("j"), ord("k"), ord("/"), 10])
    Viewer(screen, "\n".join(["first", "needle", *[f"line {i}" for i in range(20)]])).display()
    assert any("Viewer help" in line for line in screen.lines) or screen.lines


def test_tool_dict_creation_and_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    path = case / "system" / "sampleDict"
    assert tool_dicts_ui._ensure_tool_dict(Screen([ord("n")]), case, "sample", path, None) is False
    monkeypatch.setattr(
        tool_dicts_ui,
        "ensure_dict",
        lambda *_a, **_k: SimpleNamespace(created=True),
    )
    assert tool_dicts_ui._ensure_tool_dict(Screen([ord("y")]), case, "sample", path, ["foamGet"]) is True
    path.parent.mkdir()
    path.write_text("FoamFile {}\nfields (U);\n")
    assert tool_dicts_ui._ensure_tool_dict(Screen(), case, "sample", path, None) is True

    viewed: list[str] = []

    class Preview:
        def __init__(self, _screen: object, content: str) -> None:
            viewed.append(content)

        def display(self) -> None:
            return None

    monkeypatch.setattr(tool_dicts_ui, "Viewer", Preview)
    monkeypatch.setattr(tool_dicts_ui.foamlib_integration, "is_foam_file", lambda _path: True)
    monkeypatch.setattr(tool_dicts_ui.foamlib_integration, "list_keywords", lambda _path: ["fields"])
    tool_dicts_ui._open_dict_preview(Screen(), path)
    assert "Keys:" in viewed[-1]
    assert "fields" in viewed[-1]


def test_tool_dict_preview_reports_read_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(tool_dicts_ui, "_show_message", lambda _screen, message: messages.append(message))
    tool_dicts_ui._open_dict_preview(Screen(), tmp_path / "missing")
    assert messages[-1].startswith("Failed to read missing:")


def test_help_wrappers_and_tool_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(help_ui.help_registry, "context", lambda name: [name])
    assert help_ui.main_menu_help() == ["main"]
    assert help_ui.preprocessing_help() == ["preprocessing"]
    assert help_ui.physics_help() == ["physics"]
    assert help_ui.simulation_help() == ["simulation"]
    assert help_ui.postprocessing_help() == ["postprocessing"]
    assert help_ui.config_help() == ["config"]
    assert help_ui.tools_help() == ["tools"]
    assert help_ui.tools_physics_help() == ["tools_physics"]
    assert help_ui.diagnostics_help() == ["diagnostics"]
    assert help_ui.clean_case_help() == ["clean"]

    viewed: list[str] = []
    monkeypatch.setattr(help_ui, "tool_help", lambda _name: ["line"])
    monkeypatch.setattr(
        help_ui, "Viewer", lambda _screen, content: SimpleNamespace(display=lambda: viewed.append(content))
    )
    help_ui.show_tool_help(Screen(), "Title", "tool")
    assert viewed == ["Title\n\nline"]


def test_high_speed_helper_success_missing_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    zero = case / "0"
    zero.mkdir(parents=True)
    for field in ("U", "p"):
        (zero / field).write_text("internalField uniform 0;\n")
    messages: list[str] = []
    monkeypatch.setattr(high_speed, "_collect_inputs", lambda _screen: (2.0, 300.0, 1.4, 287.0, 101325.0))
    monkeypatch.setattr(high_speed, "_confirm_apply", lambda *_a: True)
    monkeypatch.setattr(high_speed, "_show_message", lambda _screen, message: messages.append(message))
    monkeypatch.setattr(high_speed, "apply_edit_plan", lambda *_a: [])
    high_speed.high_speed_helper_screen(Screen(), case)
    assert messages[-1] == "Updated internalField for U and p."

    (zero / "p").unlink()
    high_speed.high_speed_helper_screen(Screen(), case)
    assert messages[-1] == "Missing 0/U or 0/p file."
    (zero / "p").write_text("x")
    monkeypatch.setattr(high_speed, "apply_edit_plan", lambda *_a: ["bad"])
    high_speed.high_speed_helper_screen(Screen(), case)
    assert messages[-1] == "Failed to update one or more fields."


def test_high_speed_input_and_confirmation_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    values = iter(["", "bad"])
    messages: list[str] = []
    monkeypatch.setattr(high_speed, "prompt_input", lambda *_a, **_k: next(values))
    monkeypatch.setattr(high_speed, "_show_message", lambda _screen, message: messages.append(message))
    assert high_speed._prompt_float(Screen(), "Mach", default=2.0) == 2.0
    assert high_speed._prompt_float(Screen(), "Mach", default=2.0) is None
    assert messages == ["Invalid number for Mach."]
    assert high_speed._confirm_apply(Screen([ord("y")]), 1.0, 2.0) is True
    assert high_speed._confirm_apply(Screen([ord("n")]), 1.0, 2.0) is False


def test_high_speed_collects_complete_input_set(monkeypatch: pytest.MonkeyPatch) -> None:
    values = iter([2.0, 300.0, 1.4, 287.0, 101325.0])
    monkeypatch.setattr(high_speed, "_prompt_float", lambda *_a, **_k: next(values))
    assert high_speed._collect_inputs(Screen()) == (2.0, 300.0, 1.4, 287.0, 101325.0)
    monkeypatch.setattr(high_speed, "_prompt_float", lambda *_a, **_k: None)
    assert high_speed._collect_inputs(Screen()) is None


def test_blockmesh_success_viewer_search_and_foamlib_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    path = case / "system" / "blockMeshDict"
    path.parent.mkdir(parents=True)
    path.write_text("x")
    monkeypatch.setattr(blockmesh_helper, "get_dict_path", lambda _name: "system/blockMeshDict")
    monkeypatch.setattr(
        blockmesh_helper,
        "_load_blockmesh_details",
        lambda _path: ([(0.0, 0.0, 0.0)], [("hex", [0])], ["walls"], 1),
    )
    shown: list[list[str]] = []
    monkeypatch.setattr(blockmesh_helper, "_blockmesh_viewer", lambda _s, lines, _path: shown.append(lines))
    blockmesh_helper.blockmesh_helper_screen(Screen(), case)
    assert any("Vertices: 1" in line for line in shown[0])
    monkeypatch.setattr(blockmesh_helper, "prompt_input", lambda *_a: "needle")
    assert blockmesh_helper._blockmesh_search(Screen(), ["a", "needle"], 0) == 1

    adapter = blockmesh_helper.foamlib_integration
    monkeypatch.setattr(adapter, "read_entry_node", lambda *_a: (_ for _ in ()).throw(ValueError("bad")))
    assert blockmesh_helper._load_blockmesh_details_foamlib(path) == ([], [], [], 0)


def test_initial_field_error_edit_and_scroll(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    field = case / "0" / "phi"
    field.parent.mkdir(parents=True)
    field.write_text("x")
    monkeypatch.setattr(initial_conditions, "read_entry", lambda *_a: (_ for _ in ()).throw(OpenFOAMError("bad")))
    row = initial_conditions._build_initial_field_row(field, "phi")
    assert row.error == "bad"
    messages: list[str] = []
    monkeypatch.setattr(initial_conditions, "_show_message", lambda _screen, message: messages.append(message))
    initial_conditions._edit_initial_field(Screen(), case, field, "phi")
    assert messages[-1] == "Failed to read internalField: bad"

    state = initial_conditions._InitialState(row=9, scroll=9)
    initial_conditions._adjust_initial_scroll(state, 0, 2)
    assert state == initial_conditions._InitialState()


def test_initial_conditions_table_renders_status_and_extra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(initial_conditions.curses, "color_pair", lambda value: value)
    monkeypatch.setattr(initial_conditions.curses, "A_REVERSE", 1)
    rows = [
        initial_conditions._InitialFieldRow(
            name="U",
            path=tmp_path / "U",
            type_label="vector",
            preview="uniform",
            extra="(1 0 0)",
        ),
        initial_conditions._InitialFieldRow(
            name="p",
            path=tmp_path / "p",
            type_label="scalar",
            preview="uniform",
        ),
    ]
    screen = Screen(width=100)
    state = initial_conditions._InitialState(row=1)
    initial_conditions._draw_initial_conditions_table(screen, rows, state, "0.orig", "original fields")
    assert any("Initial conditions (0.orig)" in line for line in screen.lines)
    assert any("(1 0 0)" in line for line in screen.lines)
    assert state.row == 1
