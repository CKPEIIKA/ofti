from __future__ import annotations

import curses
from pathlib import Path

import pytest

from ofti.core.boundary import BoundaryCell, BoundaryMatrix
from ofti.ui_curses import blockmesh_helper as bmh
from ofti.ui_curses import boundary_matrix as bm
from ofti.ui_curses import high_speed as hs
from ofti.ui_curses import initial_conditions as ic
from ofti.ui_curses import openfoam_env as ofenv


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

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")

    def derwin(self, *_args: object) -> _Screen:
        return self

    def noutrefresh(self) -> None:
        return None

    def attron(self, *_args: object) -> None:
        return None

    def attroff(self, *_args: object) -> None:
        return None


def _matrix() -> BoundaryMatrix:
    return BoundaryMatrix(
        fields=["U", "p"],
        patches=["inlet", "wall", "processor0"],
        patch_types={"inlet": "patch", "wall": "wall", "processor0": "processor"},
        data={
            "inlet": {
                "U": BoundaryCell("OK", "fixedValue", "uniform (1 0 0)"),
                "p": BoundaryCell("MISSING", "missing", ""),
            },
            "wall": {
                "U": BoundaryCell("WILDCARD", "zeroGradient", ""),
                "p": BoundaryCell("MISSING", "missing", ""),
            },
            "processor0": {
                "U": BoundaryCell("OK", "processor", ""),
                "p": BoundaryCell("MISSING", "missing", ""),
            },
        },
    )


def test_boundary_matrix_helpers_core(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    screen = _Screen()
    matrix = _matrix()

    monkeypatch.setattr(bm.curses, "color_pair", lambda value: value * 10)
    assert bm._boundary_matrix_layout(120).visible_cols >= 1
    assert bm._format_cell_label(BoundaryCell("OK", "fixedValue", ""), 8).strip() == "fixedVa"
    assert bm._cell_attr(BoundaryCell("MISSING", "missing", "")) > 0
    assert bm._missing_boundary_fields(matrix) == ["p"]
    assert "processor0" not in bm._visible_patches(matrix, True)

    state = bm._MatrixState(row=99, col=0, row_scroll=0, col_scroll=0, hide_special=False)
    normalized = bm._normalize_state(state, ["inlet", "wall"])
    assert normalized.row == 1
    assert bm._handle_navigation_key(matrix, ["inlet", "wall"], curses.KEY_DOWN, normalized) is True

    row_scroll, col_scroll = bm._adjust_scroll(screen, matrix.patches, matrix, 2, 1, 0, 0)
    assert row_scroll >= 0
    assert col_scroll >= 0

    captured: dict[str, object] = {}

    def fake_apply(_case_path: Path, _plan: object) -> list[str]:
        captured["called"] = True
        return []

    monkeypatch.setattr(bm, "build_edit_plan", lambda edits: edits)
    monkeypatch.setattr(bm, "apply_edit_plan", fake_apply)
    case = tmp_path / "case"
    case.mkdir()
    (case / "0").mkdir()
    assert bm._apply_boundary_cell(screen, case, matrix, "inlet", "U", "fixedValue", "uniform (2 0 0)") is True
    assert captured["called"] is True


def test_boundary_matrix_actions_and_screen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    matrix = _matrix()

    messages: list[str] = []
    monkeypatch.setattr(bm, "_show_message", lambda _s, text: messages.append(text))
    monkeypatch.setattr(bm, "_prompt_value", lambda *_a, **_k: "wall.*")
    monkeypatch.setattr(bm, "_prompt_bc_type", lambda *_a, **_k: "fixedValue")
    monkeypatch.setattr(bm, "_apply_boundary_cell", lambda *_a, **_k: True)
    bm._apply_patch_group(screen, case, matrix, "U")
    bm._apply_field_all(screen, case, matrix, "U")

    monkeypatch.setattr(bm, "_snippet_options", lambda _field: [])
    bm._paste_boundary_snippet(screen, case, matrix, "inlet", "U")
    assert messages[-1] == "No snippets available for this field."

    monkeypatch.setattr(bm, "change_patch_type", lambda *_a, **_k: (True, ""))
    monkeypatch.setattr(bm, "rename_boundary_patch", lambda *_a, **_k: (True, ""))
    state = bm._MatrixState()
    action = bm._handle_boundary_action_key(screen, case, matrix, matrix.patches, ord("f"), state)
    assert isinstance(action, bm._MatrixState)
    assert action.hide_special
    assert bm._handle_boundary_action_key(screen, case, matrix, matrix.patches, ord("t"), state) == "reload"
    assert bm._handle_boundary_action_key(screen, case, matrix, matrix.patches, ord("r"), state) == "reload"

    monkeypatch.setattr(bm, "_load_boundary_matrix", lambda *_a, **_k: BoundaryMatrix([], [], {}, {}))
    bm.boundary_matrix_screen(screen, case)
    assert "requires patches and 0/* fields" in messages[-1]

    calls = iter(["reload", "back"])
    monkeypatch.setattr(bm, "_load_boundary_matrix", lambda *_a, **_k: matrix)
    monkeypatch.setattr(bm, "_draw_boundary_matrix", lambda *_a, **_k: None)
    monkeypatch.setattr(bm, "_handle_boundary_key", lambda *_a, **_k: next(calls))
    bm.boundary_matrix_screen(screen, case)


def test_boundary_matrix_draw_and_key_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    matrix = _matrix()
    screen = _Screen(height=12, width=100)
    monkeypatch.setattr(bm.curses, "color_pair", lambda value: value)
    monkeypatch.setattr(bm.curses, "A_REVERSE", 0x10000)
    monkeypatch.setattr(bm.curses, "A_BOLD", 0x20000)
    monkeypatch.setattr(bm.curses, "A_DIM", 0x40000)
    bm._draw_boundary_matrix(screen, matrix, matrix.patches, 0, 0, 0, 0, False)
    bm._show_loading_status(screen, "loading")
    monkeypatch.setattr(bm, "build_boundary_matrix", lambda _case: matrix)
    assert bm._load_boundary_matrix(screen, tmp_path, "msg") is matrix

    # _prompt_value and _prompt_bc_type branches.
    monkeypatch.setattr(bm, "prompt_input", lambda *_a, **_k: "")
    assert bm._prompt_value(screen, "name", "current") == "current"

    class MenuCustom:
        def __init__(self, *_a, **_k) -> None:
            return None

        def navigate(self) -> int:
            return len(bm._field_type_options("U"))

    monkeypatch.setattr(bm, "Menu", MenuCustom)
    monkeypatch.setattr(bm, "_prompt_value", lambda *_a, **_k: "customBC")
    assert bm._prompt_bc_type(screen, "U", "") == "customBC"

    # Enter branch in _handle_boundary_key.
    edited: list[str] = []
    monkeypatch.setattr(bm, "_handle_boundary_action_key", lambda *_a, **_k: None)
    monkeypatch.setattr(bm, "_handle_navigation_key", lambda *_a, **_k: False)
    monkeypatch.setattr(bm, "_edit_boundary_cell", lambda *_a, **_k: edited.append("edit"))
    state = bm._MatrixState()
    result = bm._handle_boundary_key(screen, tmp_path, matrix, matrix.patches, 10, state)
    assert isinstance(result, bm._MatrixState)
    assert edited == ["edit"]


def test_boundary_matrix_apply_group_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    matrix = _matrix()
    screen = _Screen()
    messages: list[str] = []
    monkeypatch.setattr(bm, "_show_message", lambda _s, text: messages.append(text))

    # invalid regex
    monkeypatch.setattr(bm, "_prompt_value", lambda *_a, **_k: "[")
    bm._apply_patch_group(screen, case, matrix, "U")
    assert "Invalid regex:" in messages[-1]

    # valid regex with no matches
    monkeypatch.setattr(bm, "_prompt_value", lambda *_a, **_k: "^zzz$")
    bm._apply_patch_group(screen, case, matrix, "U")
    assert "No patches matched the regex." in messages[-1]

    # field all with no-value type
    monkeypatch.setattr(bm, "_prompt_bc_type", lambda *_a, **_k: "zeroGradient")
    called: list[str] = []
    monkeypatch.setattr(bm, "_apply_boundary_cell", lambda *_a, **_k: called.append("x") or True)
    bm._apply_field_all(screen, case, matrix, "U")
    assert len(called) == len(matrix.patches)


def test_blockmesh_helper_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    screen = _Screen(keys=[ord("h")])
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(bmh, "_show_message", lambda _s, text: messages.append(text))
    monkeypatch.setattr(bmh, "get_dict_path", lambda _name: "system/blockMeshDict")
    bmh.blockmesh_helper_screen(screen, case)
    assert "Missing system/blockMeshDict." in messages[-1]

    (case / "system").mkdir()
    dict_path = case / "system" / "blockMeshDict"
    dict_path.write_text("dummy\n")
    monkeypatch.setattr(bmh, "_load_blockmesh_details", lambda _path: ([], [], [], 0))
    bmh.blockmesh_helper_screen(screen, case)
    assert "No vertices found" in messages[-1]

    viewed: list[list[str]] = []
    monkeypatch.setattr(
        bmh,
        "_load_blockmesh_details",
        lambda _path: ([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [("hex", [0, 1])], ["inlet"], 1),
    )
    monkeypatch.setattr(bmh, "_blockmesh_viewer", lambda _s, lines, _p: viewed.append(lines))
    bmh.blockmesh_helper_screen(screen, case)
    assert any("Vertices: 2" in line for line in viewed[0])

    monkeypatch.setattr(bmh, "prompt_input", lambda *_a, **_k: "needle")
    assert bmh._blockmesh_search(screen, ["a", "needle line"], 0) == 1
    assert bmh._blockmesh_nav(0, curses.KEY_DOWN, 1, 10, 20) == 1


def test_high_speed_helpers_and_screen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    screen = _Screen(keys=[ord("y"), ord("h"), ord("h")])
    monkeypatch.setattr(hs, "prompt_input", lambda *_a, **_k: "")
    assert hs._prompt_float(screen, "Mach", default=2.0) == 2.0
    monkeypatch.setattr(hs, "prompt_input", lambda *_a, **_k: "3.5")
    assert hs._prompt_float(screen, "Mach", default=2.0) == 3.5
    monkeypatch.setattr(hs, "prompt_input", lambda *_a, **_k: "bad")
    assert hs._prompt_float(screen, "Mach", default=2.0) is None
    assert hs._confirm_apply(_Screen(keys=[ord("y")]), 10.0, 20.0) is True

    case = tmp_path / "case"
    case.mkdir()
    (case / "0").mkdir()
    (case / "0" / "U").write_text("ok\n")
    (case / "0" / "p").write_text("ok\n")
    messages: list[str] = []
    monkeypatch.setattr(hs, "_show_message", lambda _s, text: messages.append(text))
    monkeypatch.setattr(hs, "_collect_inputs", lambda _s: (2.0, 300.0, 1.4, 287.0, 101325.0))
    monkeypatch.setattr(hs, "compute_high_speed_fields", lambda *_a, **_k: (500.0, 200000.0))
    monkeypatch.setattr(hs, "_confirm_apply", lambda *_a, **_k: True)
    monkeypatch.setattr(hs, "build_edit_plan", lambda edits: edits)
    monkeypatch.setattr(hs, "apply_edit_plan", lambda *_a, **_k: [])
    hs.high_speed_helper_screen(screen, case)
    assert "Updated internalField" in messages[-1]


def test_initial_conditions_helpers_and_screen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert ic._compact_preview("abcdef", max_len=5).endswith("...")
    assert ic._format_preview("uniform 100")[0] == "uniform"
    state = ic._InitialState(row=10, scroll=0)
    ic._adjust_initial_scroll(state, total=2, visible=1)
    assert state.row == 1

    field_path = tmp_path / "U"
    field_path.write_text("dummy\n")
    monkeypatch.setattr(ic, "read_entry", lambda *_a, **_k: "uniform (0 0 0)")
    monkeypatch.setattr(ic, "choose_validator", lambda *_a, **_k: (lambda _v: None, "vector"))
    monkeypatch.setattr(ic, "detect_type_with_foamlib", lambda *_a, **_k: (lambda _v: None, "vector"))
    row = ic._build_initial_field_row(field_path, "U")
    assert row.type_label == "vector"

    edited: dict[str, bool] = {"called": False}

    class FakeEditor:
        def __init__(self, *_a, **_k) -> None:
            return None

        def edit(self) -> None:
            edited["called"] = True

    monkeypatch.setattr(ic, "EntryEditor", FakeEditor)
    case = tmp_path / "case"
    case.mkdir()
    ic._edit_initial_field(_Screen(), case, field_path, "U")
    assert edited["called"] is True

    screen = _Screen(keys=[ord("h")])
    messages: list[str] = []
    monkeypatch.setattr(ic, "_show_message", lambda _s, text: messages.append(text))
    monkeypatch.setattr(ic, "zero_dir", lambda _case: tmp_path / "missing")
    ic.initial_conditions_screen(screen, case)
    assert "No 0/ or 0.orig directory found." in messages[-1]


def test_openfoam_env_helpers_and_screen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    screen = _Screen(keys=[ord("a"), curses.KEY_BACKSPACE, ord("b"), 10])
    assert ofenv._prompt_text(screen, "path: ") == "b"

    cfg = ofenv.get_config()
    ofenv._set_openfoam_bashrc(None)
    assert cfg.openfoam_bashrc is None

    bashrc = tmp_path / "bashrc"
    bashrc.write_text("ok\n")
    monkeypatch.setattr(ofenv, "wm_project_dir_from_bashrc", lambda _p: "/wm")
    ofenv._set_openfoam_bashrc(bashrc)
    assert ofenv.get_config().openfoam_bashrc == str(bashrc)

    class FakeMenu:
        def __init__(self, *_a, **_k) -> None:
            return None

        def navigate(self) -> int:
            return 0

    monkeypatch.setattr(ofenv, "Menu", FakeMenu)
    monkeypatch.setattr(ofenv, "resolve_openfoam_bashrc", lambda: bashrc)
    monkeypatch.setattr(ofenv, "auto_detect_bashrc_paths", lambda: [bashrc])
    shown: list[str] = []
    monkeypatch.setattr(ofenv, "_show_message", lambda _s, text: shown.append(text))
    ofenv.openfoam_env_screen(screen)
    assert "Using OpenFOAM bashrc" in shown[-1]

    class FakeMenuManual(FakeMenu):
        def navigate(self) -> int:
            return 1

    monkeypatch.setattr(ofenv, "Menu", FakeMenuManual)
    monkeypatch.setattr(ofenv, "_prompt_text", lambda *_a, **_k: str(tmp_path / "missing"))
    ofenv.openfoam_env_screen(screen)
    assert "Path not found" in shown[-1]
