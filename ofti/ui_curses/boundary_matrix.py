from __future__ import annotations

import curses
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.boundary import BoundaryCell, BoundaryMatrix, build_boundary_matrix, zero_dir
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import write_entry


def boundary_matrix_screen(stdscr: Any, case_path: Path) -> None:
    matrix = build_boundary_matrix(case_path)
    if not matrix.patches or not matrix.fields:
        _show_message(stdscr, "Boundary matrix requires patches and 0/* fields.")
        return

    row = 0
    col = 0
    row_scroll = 0
    col_scroll = 0

    while True:
        _draw_boundary_matrix(stdscr, matrix, row, col, row_scroll, col_scroll)
        key = stdscr.getch()

        if key_in(key, get_config().keys.get("quit", [])):
            raise QuitAppError()
        if key_in(key, get_config().keys.get("back", [])) and key != ord("h"):
            return
        if key in (curses.KEY_UP, ord("k")):
            row = (row - 1) % len(matrix.patches)
        elif key in (curses.KEY_DOWN, ord("j")):
            row = (row + 1) % len(matrix.patches)
        elif key in (curses.KEY_LEFT, ord("h")):
            col = max(0, col - 1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            col = min(len(matrix.fields) - 1, col + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            _edit_boundary_cell(stdscr, case_path, matrix, row, col)

        row_scroll, col_scroll = _adjust_scroll(stdscr, matrix, row, col, row_scroll, col_scroll)


def _adjust_scroll(
    stdscr: Any,
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

    row_scroll = max(0, min(row_scroll, max(0, len(matrix.patches) - visible_rows)))
    col_scroll = max(0, min(col_scroll, max(0, len(matrix.fields) - visible_cols)))
    return row_scroll, col_scroll


def _draw_boundary_matrix(
    stdscr: Any,
    matrix: BoundaryMatrix,
    row: int,
    col: int,
    row_scroll: int,
    col_scroll: int,
) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    layout = _boundary_matrix_layout(width)
    fields = _draw_boundary_header(stdscr, matrix, col_scroll, layout, width)
    _draw_boundary_rows(stdscr, matrix, row, row_scroll, fields, layout, height, width)
    _draw_boundary_status(stdscr, matrix, row, col, height, width)
    stdscr.refresh()


@dataclass(frozen=True)
class _BoundaryLayout:
    patch_col: int
    type_col: int
    col_width: int
    visible_cols: int


def _boundary_matrix_layout(width: int) -> _BoundaryLayout:
    patch_col = 20
    type_col = 12
    col_width = 14
    visible_cols = max(1, (width - patch_col - type_col - 2) // col_width)
    return _BoundaryLayout(patch_col, type_col, col_width, visible_cols)


def _draw_boundary_header(
    stdscr: Any,
    matrix: BoundaryMatrix,
    col_scroll: int,
    layout: _BoundaryLayout,
    width: int,
) -> list[str]:
    back_hint = key_hint("back", "h")
    header = f"Boundary Matrix (Enter: edit  {back_hint}: back)"
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
    row: int,
    row_scroll: int,
    fields: list[str],
    layout: _BoundaryLayout,
    height: int,
    width: int,
) -> None:
    visible_rows = max(1, height - 4)
    rows = matrix.patches[row_scroll : row_scroll + visible_rows]
    for idx, patch in enumerate(rows):
        line = _format_boundary_row(matrix, patch, fields, layout)
        with suppress(curses.error):
            if row_scroll + idx == row:
                stdscr.attron(curses.color_pair(1))
            stdscr.addstr(3 + idx, 0, line[: max(1, width - 1)])
            if row_scroll + idx == row:
                stdscr.attroff(curses.color_pair(1))


def _format_boundary_row(
    matrix: BoundaryMatrix,
    patch: str,
    fields: list[str],
    layout: _BoundaryLayout,
) -> str:
    patch_type = matrix.patch_types.get(patch, "")
    line = patch.ljust(layout.patch_col) + patch_type.ljust(layout.type_col)
    for field in fields:
        cell = matrix.data.get(patch, {}).get(field)
        line += _format_cell_label(cell, layout.col_width)
    return line


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


def _draw_boundary_status(
    stdscr: Any,
    matrix: BoundaryMatrix,
    row: int,
    col: int,
    height: int,
    width: int,
) -> None:
    status = f"Patch {row + 1}/{len(matrix.patches)} | Field {col + 1}/{len(matrix.fields)}"
    with suppress(curses.error):
        stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(height - 1, 0, status[: max(1, width - 1)].ljust(width - 1))
        stdscr.attroff(curses.A_REVERSE)


def _edit_boundary_cell(
    stdscr: Any,
    case_path: Path,
    matrix: BoundaryMatrix,
    row: int,
    col: int,
) -> None:
    patch = matrix.patches[row]
    field = matrix.fields[col]
    file_path = zero_dir(case_path) / field
    cell = matrix.data.get(patch, {}).get(field)
    current_type = cell.bc_type if cell else ""
    current_value = cell.value if cell else ""

    bc_type = _prompt_value(stdscr, f"{patch}/{field} type", current_type)
    if bc_type is None:
        return
    bc_value = _prompt_value(stdscr, f"{patch}/{field} value", current_value)
    if bc_value is None:
        return
    if bc_type == current_type and bc_value == current_value:
        return

    type_key = f"boundaryField.{patch}.type"
    value_key = f"boundaryField.{patch}.value"
    write_entry(file_path, type_key, bc_type)
    if bc_value:
        write_entry(file_path, value_key, bc_value)

    matrix.data[patch][field] = BoundaryCell("OK", bc_type or "unknown", bc_value or "")


def _prompt_value(stdscr: Any, label: str, current: str) -> str | None:
    stdscr.clear()
    stdscr.addstr(f"{label} (blank to keep current):\n")
    if current:
        stdscr.addstr(f"current: {current}\n")
    stdscr.addstr("> ")
    stdscr.refresh()
    try:
        value = stdscr.getstr().decode().strip()
    except OSError:
        return None
    if not value:
        return current
    return value


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    stdscr.addstr("Press any key to continue.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()
