from __future__ import annotations

import curses
import types
from pathlib import Path

import pytest

from ofti.app import helpers
from ofti.foam.config import Config
from ofti.foam.exceptions import QuitAppError
from ofti.tools import tool_dicts_foamcalc as foamcalc
from ofti.tools import tool_dicts_postprocess as postprocess
from ofti.tools import tool_dicts_prompts as prompts
from ofti.ui_curses import blockmesh_helper as bmh
from ofti.ui_curses import initial_conditions as ic


class _Screen:
    def __init__(self, keys: list[int] | None = None, height: int = 24, width: int = 90) -> None:
        self._keys = list(keys or [])
        self.height = height
        self.width = width
        self.lines: list[str] = []

    def clear(self) -> None:
        self.lines.clear()

    def erase(self) -> None:
        self.lines.clear()

    def getmaxyx(self) -> tuple[int, int]:
        return (self.height, self.width)

    def addstr(self, *args: object) -> None:
        self.lines.append(str(args[-1]))

    def refresh(self) -> None:
        return None

    def move(self, *_args: object) -> None:
        return None

    def clrtoeol(self) -> None:
        return None

    def attron(self, *_args: object) -> None:
        return None

    def attroff(self, *_args: object) -> None:
        return None

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")


class _Menu:
    def __init__(self, choice: int) -> None:
        self._choice = choice

    def navigate(self) -> int:
        return self._choice


def _cfg() -> Config:
    cfg = Config()
    cfg.keys["quit"] = ["Q"]
    return cfg


def test_app_helpers_extra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    screen = _Screen(keys=[ord("q")])
    cfg = _cfg()
    cfg.keys["quit"] = ["q"]
    monkeypatch.setattr(helpers, "get_config", lambda: cfg)
    with pytest.raises(QuitAppError):
        helpers.show_message(screen, "hello")

    root = tmp_path / "root"
    root.mkdir()
    (root / ".hidden").write_text("x")
    (root / "visible.txt").write_text("x")
    (root / "d").mkdir()
    dirs, files = helpers.list_dir_entries(root)
    assert [p.name for p in dirs] == ["d"]
    assert [p.name for p in files] == ["visible.txt"]

    cfg.keys["search"] = ["/"]
    cfg.keys["back"] = ["h"]
    cfg.keys["select"] = ["\n"]
    monkeypatch.setattr(helpers, "show_message", lambda *_a, **_k: None)
    monkeypatch.setattr(helpers, "prompt_input", lambda *_a, **_k: "vis")
    chooser = _Screen(keys=[ord("/"), ord("e"), ord("h"), ord("q")])
    with pytest.raises(QuitAppError):
        helpers.select_case_directory(chooser, root)

    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    assert helpers.select_case_directory(_Screen(keys=[ord("e")]), case) == case

    # prompt_command paths: typing, cursor moves, tab and enter.
    cmd = helpers.prompt_command(
        _Screen(keys=[ord("a"), ord("b"), curses.KEY_LEFT, curses.KEY_RIGHT, 9, 10]),
        ["abc", "abd"],
    )
    assert cmd
    assert helpers.menu_scroll(current=10, scroll=0, stdscr=_Screen(height=5), total=100, header_rows=1) >= 0

    state = types.SimpleNamespace(no_foam=False, no_foam_reason=None)
    helpers.set_no_foam_mode(state, True, "x")
    assert state.no_foam is True
    helpers.set_no_foam_mode(state, False, None)
    assert state.no_foam is False


def test_app_helpers_create_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    current = tmp_path / "dst"
    current.mkdir()
    template = tmp_path / "template"
    (template / "system").mkdir(parents=True)
    (template / "system" / "controlDict").write_text("application simpleFoam;\n")
    monkeypatch.setattr(helpers, "_list_example_cases", lambda: [template])

    class MenuPick:
        def __init__(self, *_a, **_k) -> None:
            return None

        def navigate(self) -> int:
            return 0

    monkeypatch.setattr(helpers, "Menu", MenuPick)
    monkeypatch.setattr(helpers, "prompt_input", lambda *_a, **_k: "newCase")
    result = helpers._create_case_from_example(_Screen(), current)
    assert result is not None and result.name == "newCase"


def test_blockmesh_helper_extra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    path = case / "blockMeshDict"
    path.write_text("dummy\n")

    monkeypatch.setattr(bmh, "foamlib_integration", types.SimpleNamespace(available=lambda: False))
    monkeypatch.setattr(bmh, "read_entry", lambda _p, key: {"vertices": "(0 0 0)", "blocks": "", "boundary": "", "edges": "("}[key])
    vertices, blocks, boundaries, edges = bmh._load_blockmesh_details_text(path)
    assert edges >= 1
    assert isinstance(vertices, list) and isinstance(blocks, list) and isinstance(boundaries, list)

    monkeypatch.setattr(
        bmh,
        "foamlib_integration",
        types.SimpleNamespace(
            available=lambda: True,
            is_foam_file=lambda _p: True,
            read_entry_node=lambda _p, _k: [],
        ),
    )
    assert bmh._load_blockmesh_details(path)[0] == []

    messages: list[str] = []
    monkeypatch.setattr(bmh, "_show_message", lambda _s, text: messages.append(text))
    monkeypatch.setattr(bmh.curses, "endwin", lambda: None)
    monkeypatch.setattr(bmh, "resolve_executable", lambda _name: (_ for _ in ()).throw(OSError("missing")))
    bmh._open_file_in_editor(_Screen(), path)
    assert "Failed to run" in messages[-1]


def test_initial_conditions_extra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    zero = case / "0"
    zero.mkdir()
    (zero / "U").write_text("x\n")

    rows = [ic._InitialFieldRow(name="U", path=zero / "U", type_label="vector", preview="uniform", extra="(0 0 0)")]
    monkeypatch.setattr(ic, "zero_dir", lambda _case: zero)
    monkeypatch.setattr(ic, "list_field_files", lambda _case: ["U"])
    monkeypatch.setattr(ic, "_build_initial_rows", lambda *_a, **_k: rows)
    monkeypatch.setattr(ic, "_build_initial_field_row", lambda *_a, **_k: rows[0])
    edited: list[str] = []
    monkeypatch.setattr(ic, "_edit_initial_field", lambda *_a, **_k: edited.append("edit"))
    monkeypatch.setattr(ic, "_draw_initial_conditions_table", lambda *_a, **_k: None)
    cfg = _cfg()
    cfg.keys["top"] = ["g"]
    cfg.keys["bottom"] = ["G"]
    cfg.keys["back"] = ["h"]
    cfg.keys["select"] = ["\n"]
    monkeypatch.setattr(ic, "get_config", lambda: cfg)
    ic.initial_conditions_screen(_Screen(keys=[curses.KEY_DOWN, curses.KEY_UP, ord("g"), ord("G"), 10, ord("h")]), case)
    assert edited == ["edit"]

    # draw table path
    monkeypatch.setattr(ic.curses, "color_pair", lambda value: value)
    ic._draw_initial_conditions_table(_Screen(height=8, width=50), rows, ic._InitialState(), "0", "status")


def test_tool_dict_prompts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    monkeypatch.setattr(foamcalc, "_ensure_tool_dict", lambda *_a, **_k: True)
    monkeypatch.setattr(foamcalc, "latest_time", lambda _case: "1")
    monkeypatch.setattr(foamcalc, "build_menu", lambda *_a, **_k: _Menu(0))
    called: list[list[str]] = []
    monkeypatch.setattr(foamcalc, "_run_simple_tool", lambda *_a, **_k: called.append(list(_a[3])))
    foamcalc.foam_calc_prompt(screen, case)
    assert called[-1] == ["foamCalc"]

    monkeypatch.setattr(postprocess, "_ensure_tool_dict", lambda *_a, **_k: True)
    monkeypatch.setattr(postprocess, "latest_time", lambda _case: "1")
    monkeypatch.setattr(postprocess, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(postprocess, "_run_simple_tool", lambda *_a, **_k: called.append(list(_a[3])))
    postprocess.post_process_prompt(screen, case)
    assert called[-1][:2] == ["postProcess", "-latestTime"]

    monkeypatch.setattr(prompts, "_ensure_tool_dict", lambda *_a, **_k: True)
    monkeypatch.setattr(prompts, "prompt_args_line", lambda *_a, **_k: ["-latestTime"])
    monkeypatch.setattr(prompts, "_run_simple_tool", lambda *_a, **_k: called.append(list(_a[3])))
    prompts.topo_set_prompt(screen, case)
    prompts.set_fields_prompt(screen, case)
    assert any(cmd[0] == "topoSet" for cmd in called)

    monkeypatch.setattr(prompts, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(prompts, "_open_dict_preview", lambda *_a, **_k: called.append(["preview"]))
    prompts.tool_dicts_screen(screen, case)
    assert called[-1] == ["preview"]
