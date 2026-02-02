from __future__ import annotations

import curses
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.boundary import (
    BoundaryCell,
    BoundaryMatrix,
    build_boundary_matrix,
    change_patch_type,
    rename_boundary_patch,
    zero_dir,
)
from ofti.core.tool_dicts_service import apply_edit_plan, build_edit_plan
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.ui_curses.help import show_tool_help
from ofti.ui_curses.inputs import prompt_input
from ofti.ui_curses.menus import Menu


def boundary_matrix_screen(stdscr: Any, case_path: Path) -> None:
    matrix = _load_boundary_matrix(stdscr, case_path)
    if not matrix.patches or not matrix.fields:
        _show_message(stdscr, "Boundary matrix requires patches and 0/* fields.")
        return

    state = _MatrixState()

    while True:
        patches = _visible_patches(matrix, state.hide_special)
        if not patches:
            patches = list(matrix.patches)
            state.hide_special = False
        state = _normalize_state(state, patches)
        _draw_boundary_matrix(
            stdscr,
            matrix,
            patches,
            state.row,
            state.col,
            state.row_scroll,
            state.col_scroll,
            state.hide_special,
        )
        key = stdscr.getch()
        action = _handle_boundary_key(
            stdscr,
            case_path,
            matrix,
            patches,
            key,
            state,
        )
        if action == "back":
            return
        if action == "reload":
            matrix = _load_boundary_matrix(stdscr, case_path, "Reloading boundary matrix...")
            state = _normalize_state(state, _visible_patches(matrix, state.hide_special))
            continue
        state = action


def _adjust_scroll(
    stdscr: Any,
    patches: list[str],
    matrix: BoundaryMatrix,
    row: int,
    col: int,
    row_scroll: int,
    col_scroll: int,
) -> tuple[int, int]:
    height, width = stdscr.getmaxyx()
    visible_rows = max(1, height - 4)
    visible_cols = max(1, (width - 24) // 14)

    if row < row_scroll:
        row_scroll = row
    elif row >= row_scroll + visible_rows:
        row_scroll = row - visible_rows + 1

    if col < col_scroll:
        col_scroll = col
    elif col >= col_scroll + visible_cols:
        col_scroll = col - visible_cols + 1

    row_scroll = max(0, min(row_scroll, max(0, len(patches) - visible_rows)))
    col_scroll = max(0, min(col_scroll, max(0, len(matrix.fields) - visible_cols)))
    return row_scroll, col_scroll


def _draw_boundary_matrix(
    stdscr: Any,
    matrix: BoundaryMatrix,
    patches: list[str],
    row: int,
    col: int,
    row_scroll: int,
    col_scroll: int,
    hide_special: bool,
) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    layout = _boundary_matrix_layout(width)
    fields = _draw_boundary_header(stdscr, matrix, col_scroll, layout, width, hide_special)
    _draw_boundary_warnings(stdscr, matrix, width)
    _draw_boundary_rows(
        stdscr,
        matrix,
        patches,
        row,
        col,
        row_scroll,
        col_scroll,
        fields,
        layout,
        height,
        width,
    )
    _draw_boundary_status(stdscr, matrix, patches, row, col, height, width, hide_special)
    stdscr.refresh()


@dataclass
class _MatrixState:
    row: int = 0
    col: int = 0
    row_scroll: int = 0
    col_scroll: int = 0
    hide_special: bool = False


def _normalize_state(state: _MatrixState, patches: list[str]) -> _MatrixState:
    if state.row >= len(patches):
        return _MatrixState(
            row=max(0, len(patches) - 1),
            col=state.col,
            row_scroll=0,
            col_scroll=state.col_scroll,
            hide_special=state.hide_special,
        )
    return state


def _handle_boundary_key(
    stdscr: Any,
    case_path: Path,
    matrix: BoundaryMatrix,
    patches: list[str],
    key: int,
    state: _MatrixState,
) -> _MatrixState | str:
    cfg = get_config()
    if key_in(key, cfg.keys.get("quit", [])):
        raise QuitAppError()
    if key_in(key, cfg.keys.get("help", [])):
        show_tool_help(stdscr, "Boundary Matrix Help", "boundaryMatrix")
        return state
    if key_in(key, cfg.keys.get("back", [])) and key != ord("h"):
        return "back"
    action = _handle_boundary_action_key(
        stdscr,
        case_path,
        matrix,
        patches,
        key,
        state,
    )
    if action is not None:
        return action

    if _handle_navigation_key(matrix, patches, key, state):
        state.row_scroll, state.col_scroll = _adjust_scroll(
            stdscr,
            patches,
            matrix,
            state.row,
            state.col,
            state.row_scroll,
            state.col_scroll,
        )
        return state

    if key in (curses.KEY_ENTER, 10, 13):
        _edit_boundary_cell(stdscr, case_path, matrix, patches[state.row], state.col)
    state.row_scroll, state.col_scroll = _adjust_scroll(
        stdscr,
        patches,
        matrix,
        state.row,
        state.col,
        state.row_scroll,
        state.col_scroll,
    )
    return state


def _handle_boundary_action_key(
    stdscr: Any,
    case_path: Path,
    matrix: BoundaryMatrix,
    patches: list[str],
    key: int,
    state: _MatrixState,
) -> _MatrixState | None:
    if key in (ord("f"), ord("F")):
        return _MatrixState(
            row=0,
            col=state.col,
            row_scroll=0,
            col_scroll=state.col_scroll,
            hide_special=not state.hide_special,
        )
    if key in (ord("p"), ord("P")):
        _paste_boundary_snippet(
            stdscr,
            case_path,
            matrix,
            patches[state.row],
            matrix.fields[state.col],
        )
        return state
    if key in (ord("g"), ord("G")):
        _apply_patch_group(
            stdscr,
            case_path,
            matrix,
            matrix.fields[state.col],
        )
        return state
    if key in (ord("a"), ord("A")):
        _apply_field_all(stdscr, case_path, matrix, matrix.fields[state.col])
        return state
    if key in (ord("t"), ord("T")):
        patch = patches[state.row]
        new_type = _prompt_value(stdscr, f"{patch} type", "")
        if not new_type:
            return state
        ok, message = change_patch_type(case_path, patch, new_type)
        if not ok:
            _show_message(stdscr, message)
        return "reload" if ok else state
    if key in (ord("r"), ord("R")):
        patch = patches[state.row]
        new_name = _prompt_value(stdscr, f"Rename {patch} to", "")
        if not new_name:
            return state
        ok, message = rename_boundary_patch(case_path, patch, new_name)
        if not ok:
            _show_message(stdscr, message)
        return "reload" if ok else state
    return None


def _handle_navigation_key(
    matrix: BoundaryMatrix,
    patches: list[str],
    key: int,
    state: _MatrixState,
) -> bool:
    if key in (curses.KEY_UP, ord("k")):
        state.row = (state.row - 1) % len(patches)
        return True
    if key in (curses.KEY_DOWN, ord("j")):
        state.row = (state.row + 1) % len(patches)
        return True
    if key in (curses.KEY_LEFT, ord("h")):
        state.col = max(0, state.col - 1)
        return True
    if key in (curses.KEY_RIGHT, ord("l")):
        state.col = min(len(matrix.fields) - 1, state.col + 1)
        return True
    return False


@dataclass(frozen=True)
class _BoundaryLayout:
    patch_col: int
    type_col: int
    col_width: int
    visible_cols: int


def _boundary_matrix_layout(width: int) -> _BoundaryLayout:
    patch_col = max(10, min(18, width // 5))
    type_col = max(8, min(14, width // 8))
    remaining = max(12, width - patch_col - type_col - 2)
    col_width = max(6, min(12, remaining // 4))
    visible_cols = max(1, remaining // col_width)
    return _BoundaryLayout(patch_col, type_col, col_width, visible_cols)


def _load_boundary_matrix(
    stdscr: Any,
    case_path: Path,
    message: str = "Loading boundary matrix...",
) -> BoundaryMatrix:
    _show_loading_status(stdscr, message)
    return build_boundary_matrix(case_path)


def _show_loading_status(stdscr: Any, message: str) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    y = max(0, height // 2)
    x = max(0, (width - len(message)) // 2)
    with suppress(curses.error):
        stdscr.addstr(y, x, message)
    stdscr.refresh()


def _draw_boundary_header(
    stdscr: Any,
    matrix: BoundaryMatrix,
    col_scroll: int,
    layout: _BoundaryLayout,
    width: int,
    hide_special: bool,
) -> list[str]:
    back_hint = key_hint("back", "h")
    filter_hint = "F: show all" if hide_special else "F: filter"
    header = (
        "Boundary Matrix (Enter: edit  P: paste  G: group  A: all  "
        f"T: type  R: rename  {filter_hint}  {back_hint}: back)"
    )
    with suppress(curses.error):
        stdscr.addstr(0, 0, header[: max(1, width - 1)])

    fields = matrix.fields[col_scroll : col_scroll + layout.visible_cols]
    header_line = "Patch".ljust(layout.patch_col) + "Type".ljust(layout.type_col)
    for field in fields:
        header_line += field[: layout.col_width - 1].ljust(layout.col_width)
    with suppress(curses.error):
        stdscr.addstr(2, 0, header_line[: max(1, width - 1)])
    return fields


def _draw_boundary_rows(
    stdscr: Any,
    matrix: BoundaryMatrix,
    patches: list[str],
    row: int,
    col: int,
    row_scroll: int,
    col_scroll: int,
    fields: list[str],
    layout: _BoundaryLayout,
    height: int,
    width: int,
) -> None:
    visible_rows = max(1, height - 4)
    rows = patches[row_scroll : row_scroll + visible_rows]
    for idx, patch in enumerate(rows):
        line_y = 3 + idx
        selected = row_scroll + idx == row
        patch_type = matrix.patch_types.get(patch, "")
        patch_label = patch.ljust(layout.patch_col)
        type_label = patch_type.ljust(layout.type_col)
        with suppress(curses.error):
            attr = curses.color_pair(1) if selected else 0
            stdscr.addstr(line_y, 0, patch_label[: max(1, width - 1)], attr)
            stdscr.addstr(
                line_y,
                layout.patch_col,
                type_label[: max(1, width - layout.patch_col - 1)],
                attr,
            )

            for col_idx, field in enumerate(fields):
                cell = matrix.data.get(patch, {}).get(field)
                label = _format_cell_label(cell, layout.col_width)
                cell_x = layout.patch_col + layout.type_col + (col_idx * layout.col_width)
                if cell_x >= width - 1:
                    break
                field_index = col_scroll + col_idx
                is_selected_cell = selected and field_index == col
                if is_selected_cell:
                    cell_attr = curses.A_REVERSE
                elif selected:
                    cell_attr = attr
                else:
                    cell_attr = _cell_attr(cell)
                stdscr.addstr(
                    line_y,
                    cell_x,
                    label[: max(1, width - cell_x - 1)],
                    cell_attr,
                )


def _format_cell_label(cell: BoundaryCell | None, col_width: int) -> str:
    label = ""
    if cell:
        if cell.status == "MISSING":
            label = "MISSING"
        elif cell.status == "WILDCARD":
            label = "wildcard"
        else:
            label = cell.bc_type
    return label[: col_width - 1].ljust(col_width)


def _cell_attr(cell: BoundaryCell | None) -> int:
    if not cell:
        return 0
    if cell.status == "MISSING":
        return curses.color_pair(4) | curses.A_BOLD
    if cell.status == "WILDCARD":
        return curses.color_pair(3)
    return curses.color_pair(2)


def _draw_boundary_warnings(stdscr: Any, matrix: BoundaryMatrix, width: int) -> None:
    missing_fields = _missing_boundary_fields(matrix)
    if not missing_fields:
        return
    warning = "Missing boundaryField in: " + ", ".join(missing_fields)
    with suppress(curses.error):
        stdscr.addstr(1, 0, warning[: max(1, width - 1)])


def _draw_boundary_status(
    stdscr: Any,
    matrix: BoundaryMatrix,
    patches: list[str],
    row: int,
    col: int,
    height: int,
    width: int,
    hide_special: bool,
) -> None:
    patch = patches[row] if patches else ""
    field = matrix.fields[col] if matrix.fields else ""
    cell = matrix.data.get(patch, {}).get(field)
    detail = ""
    if cell:
        value = cell.value or ""
        detail = f" | {cell.status}: {cell.bc_type}"
        if value:
            detail = f"{detail} = {value}"
    filter_label = "hide processor/empty" if hide_special else "all patches"
    status = (
        f"Patch {row + 1}/{len(patches)} | Field {col + 1}/{len(matrix.fields)}"
        f" | {filter_label}{detail}"
    )
    with suppress(curses.error):
        stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(height - 1, 0, status[: max(1, width - 1)].ljust(width - 1))
        stdscr.attroff(curses.A_REVERSE)


def _missing_boundary_fields(matrix: BoundaryMatrix) -> list[str]:
    missing: list[str] = []
    for field in matrix.fields:
        cells = [matrix.data.get(patch, {}).get(field) for patch in matrix.patches]
        if cells and all(cell and cell.status == "MISSING" for cell in cells):
            missing.append(field)
    return missing


def _edit_boundary_cell(
    stdscr: Any,
    case_path: Path,
    matrix: BoundaryMatrix,
    patch: str,
    col: int,
) -> None:
    field = matrix.fields[col]
    cell = matrix.data.get(patch, {}).get(field)
    current_type = cell.bc_type if cell else ""
    current_value = cell.value if cell else ""

    bc_type = _prompt_bc_type(stdscr, field, current_type)
    if bc_type is None:
        return
    bc_value = current_value
    if _type_requires_value(bc_type):
        default_value = _default_value(field, bc_type, current_value)
        bc_value = _prompt_value(
            stdscr,
            f"{patch}/{field} value",
            current_value,
            default=default_value,
        )
        if bc_value is None:
            return
    if bc_type == current_type and bc_value == current_value:
        return

    _apply_boundary_cell(stdscr, case_path, matrix, patch, field, bc_type, bc_value)


def _prompt_bc_type(stdscr: Any, field: str, current: str) -> str | None:
    options = _field_type_options(field)
    if current and current not in options:
        options.insert(0, current)
    options.append("Custom...")
    menu = Menu(stdscr, f"{field} boundary type", options)
    choice = menu.navigate()
    if choice == -1 or choice >= len(options):
        return None
    selected = options[choice]
    if selected == "Custom...":
        return _prompt_value(stdscr, f"{field} custom type", current)
    return selected


def _prompt_value(
    stdscr: Any,
    label: str,
    current: str,
    default: str | None = None,
) -> str | None:
    stdscr.clear()
    stdscr.addstr(f"{label} (blank to keep current):\n")
    if current:
        stdscr.addstr(f"current: {current}\n")
    if default and not current:
        stdscr.addstr(f"default: {default}\n")
    value = prompt_input(stdscr, "> ")
    if value is None:
        return None
    value = value.strip()
    if not value:
        return current or (default or "")
    return value


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    stdscr.addstr("Press any key to continue.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()


def _visible_patches(matrix: BoundaryMatrix, hide_special: bool) -> list[str]:
    if not hide_special:
        return list(matrix.patches)
    hidden_types = {"processor", "empty"}
    patches: list[str] = []
    for patch in matrix.patches:
        patch_type = matrix.patch_types.get(patch, "")
        if patch_type in hidden_types:
            continue
        if patch.startswith("processor"):
            continue
        patches.append(patch)
    return patches


def _apply_boundary_cell(
    stdscr: Any,
    case_path: Path,
    matrix: BoundaryMatrix,
    patch: str,
    field: str,
    bc_type: str,
    bc_value: str,
) -> bool:
    file_path = zero_dir(case_path) / field
    type_key = f"boundaryField.{patch}.type"
    value_key = f"boundaryField.{patch}.value"
    edits: list[tuple[Path, list[str], str]] = [
        (file_path, type_key.split("."), bc_type),
    ]
    if _type_requires_value(bc_type) and bc_value:
        edits.append((file_path, value_key.split("."), bc_value))
    failures = apply_edit_plan(case_path, build_edit_plan(edits))
    if failures:
        _show_message(stdscr, "Failed to update boundary entry. No changes were applied.")
        return False
    matrix.data.setdefault(patch, {})[field] = BoundaryCell(
        "OK",
        bc_type or "unknown",
        bc_value or "",
    )
    return True


def _paste_boundary_snippet(
    stdscr: Any,
    case_path: Path,
    matrix: BoundaryMatrix,
    patch: str,
    field: str,
) -> None:
    options = _snippet_options(field)
    if not options:
        _show_message(stdscr, "No snippets available for this field.")
        return
    labels = [f"{name}: {bc_type}" for name, bc_type, _ in options]
    menu = Menu(stdscr, f"{field} boundary snippets", labels)
    choice = menu.navigate()
    if choice < 0 or choice >= len(options):
        return
    _, bc_type, bc_value = options[choice]
    if _type_requires_value(bc_type):
        value = _prompt_value(stdscr, f"{patch}/{field} value", bc_value, default=bc_value)
        if value is None:
            return
        bc_value = value
    _apply_boundary_cell(stdscr, case_path, matrix, patch, field, bc_type, bc_value)


def _apply_patch_group(
    stdscr: Any,
    case_path: Path,
    matrix: BoundaryMatrix,
    field: str,
) -> None:
    pattern = _prompt_value(stdscr, "Patch regex", "", default="wall.*")
    if not pattern:
        return
    try:
        matcher = re.compile(pattern)
    except re.error as exc:
        _show_message(stdscr, f"Invalid regex: {exc}")
        return
    patches = [patch for patch in matrix.patches if matcher.search(patch)]
    if not patches:
        _show_message(stdscr, "No patches matched the regex.")
        return
    bc_type = _prompt_bc_type(stdscr, field, "")
    if bc_type is None:
        return
    bc_value = ""
    if _type_requires_value(bc_type):
        bc_value = _prompt_value(
            stdscr,
            f"{field} value",
            "",
            default=_default_value(field, bc_type, ""),
        ) or ""
    for patch in patches:
        if not _apply_boundary_cell(stdscr, case_path, matrix, patch, field, bc_type, bc_value):
            break


def _apply_field_all(
    stdscr: Any,
    case_path: Path,
    matrix: BoundaryMatrix,
    field: str,
) -> None:
    bc_type = _prompt_bc_type(stdscr, field, "")
    if bc_type is None:
        return
    bc_value = ""
    if _type_requires_value(bc_type):
        bc_value = _prompt_value(
            stdscr,
            f"{field} value",
            "",
            default=_default_value(field, bc_type, ""),
        ) or ""
    for patch in matrix.patches:
        if not _apply_boundary_cell(stdscr, case_path, matrix, patch, field, bc_type, bc_value):
            break


def _snippet_options(field: str) -> list[tuple[str, str, str]]:
    name = field.lower()
    if name in {"u", "u0", "v", "velocity"}:
        return [
            ("inlet fixedValue", "fixedValue", "uniform (1 0 0)"),
            ("outlet zeroGradient", "zeroGradient", ""),
            ("wall noSlip", "noSlip", ""),
            ("inletOutlet", "inletOutlet", "uniform (0 0 0)"),
        ]
    if name in {"p", "p_rgh", "pressure"}:
        return [
            ("outlet fixedValue", "fixedValue", "uniform 0"),
            ("inlet zeroGradient", "zeroGradient", ""),
            ("totalPressure", "totalPressure", "uniform 0"),
        ]
    if name in {"k", "epsilon", "omega", "nut", "nutilda"}:
        return [
            ("fixedValue 0", "fixedValue", "uniform 0"),
            ("zeroGradient", "zeroGradient", ""),
        ]
    if name in {"t", "temperature"}:
        return [
            ("fixedValue 300", "fixedValue", "uniform 300"),
            ("zeroGradient", "zeroGradient", ""),
        ]
    return [
        ("fixedValue 0", "fixedValue", "uniform 0"),
        ("zeroGradient", "zeroGradient", ""),
    ]


def _field_type_options(field: str) -> list[str]:
    name = field.lower()
    if name in {"u", "u0", "v", "velocity"}:
        return [
            "fixedValue",
            "zeroGradient",
            "noSlip",
            "slip",
            "inletOutlet",
            "pressureInletOutletVelocity",
            "freestream",
            "movingWallVelocity",
            "rotatingWallVelocity",
            "symmetry",
            "symmetryPlane",
            "empty",
            "calculated",
        ]
    if name in {"p", "p_rgh", "pressure"}:
        return [
            "fixedValue",
            "zeroGradient",
            "inletOutlet",
            "totalPressure",
            "freestreamPressure",
            "symmetry",
            "symmetryPlane",
            "empty",
            "calculated",
        ]
    if name in {"k", "epsilon", "omega", "nut", "nutilda"}:
        return [
            "fixedValue",
            "zeroGradient",
            "inletOutlet",
            "symmetry",
            "symmetryPlane",
            "empty",
            "calculated",
        ]
    if name in {"t", "temperature"}:
        return [
            "fixedValue",
            "zeroGradient",
            "inletOutlet",
            "symmetry",
            "symmetryPlane",
            "empty",
            "calculated",
        ]
    return [
        "fixedValue",
        "zeroGradient",
        "symmetry",
        "symmetryPlane",
        "empty",
        "calculated",
    ]


def _type_requires_value(bc_type: str) -> bool:
    no_value_types = {
        "zeroGradient",
        "noSlip",
        "slip",
        "symmetry",
        "symmetryPlane",
        "empty",
        "calculated",
    }
    return bc_type not in no_value_types


def _default_value(field: str, bc_type: str, current: str) -> str | None:
    if current:
        return None
    name = field.lower()
    defaults = {
        "u": "uniform (0 0 0)",
        "u0": "uniform (0 0 0)",
        "v": "uniform (0 0 0)",
        "velocity": "uniform (0 0 0)",
        "p": "uniform 0",
        "p_rgh": "uniform 0",
        "pressure": "uniform 0",
        "k": "uniform 0",
        "epsilon": "uniform 0",
        "omega": "uniform 0",
        "nut": "uniform 0",
        "nutilda": "uniform 0",
        "t": "uniform 300",
        "temperature": "uniform 300",
    }
    if name in defaults:
        return defaults[name]
    return "uniform 0" if bc_type == "fixedValue" else None
