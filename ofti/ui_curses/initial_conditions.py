from __future__ import annotations

import curses
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.boundary import list_field_files, zero_dir
from ofti.core.entries import Entry
from ofti.core.entry_io import read_entry
from ofti.core.entry_meta import choose_validator, detect_type_with_foamlib
from ofti.core.tool_dicts_service import apply_assignment_or_write
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import OpenFOAMError
from ofti.ui_curses.entry_editor import EntryEditor
from ofti.ui_curses.help import show_tool_help

_DERIVED_FIELDS = {
    "p_rgh",
    "phi",
    "nut",
    "nuTilda",
    "kappa",
}


@dataclass(frozen=True)
class _InitialFieldRow:
    name: str
    path: Path
    type_label: str
    preview: str
    extra: str | None = None
    error: str | None = None


@dataclass
class _InitialState:
    row: int = 0
    scroll: int = 0


def initial_conditions_screen(stdscr: Any, case_path: Path) -> None:
    zero_path = zero_dir(case_path)
    if not zero_path.is_dir():
        _show_message(stdscr, "No 0/ or 0.orig directory found.")
        return

    fields = sorted(list_field_files(case_path))
    if not fields:
        _show_message(stdscr, f"No field files found in {zero_path.name}.")
        return

    rows = _build_initial_rows(zero_path, fields)
    if not rows:
        _show_message(stdscr, "No editable initial conditions found.")
        return

    status = None
    if zero_path.name == "0.orig":
        status = "Using 0.orig (original). Changes apply to 0.orig."

    state = _InitialState()

    while True:
        _draw_initial_conditions_table(
            stdscr,
            rows,
            state,
            zero_path.name,
            status,
        )
        key = stdscr.getch()
        cfg = get_config()
        if key_in(key, cfg.keys.get("quit", [])):
            raise QuitAppError()
        if key_in(key, cfg.keys.get("help", [])):
            show_tool_help(stdscr, "Initial Conditions Help", "initialConditions")
            continue
        if key_in(key, cfg.keys.get("back", [])):
            return
        if key in (curses.KEY_UP,) or key_in(key, cfg.keys.get("up", [])):
            state.row = (state.row - 1) % len(rows)
            continue
        if key in (curses.KEY_DOWN,) or key_in(key, cfg.keys.get("down", [])):
            state.row = (state.row + 1) % len(rows)
            continue
        if key_in(key, cfg.keys.get("top", [])):
            state.row = 0
            state.scroll = 0
            continue
        if key_in(key, cfg.keys.get("bottom", [])):
            state.row = len(rows) - 1
            continue
        if key in (curses.KEY_ENTER, 10, 13) or key_in(key, cfg.keys.get("select", [])):
            current = rows[state.row]
            _edit_initial_field(stdscr, case_path, current.path, current.name)
            rows[state.row] = _build_initial_field_row(current.path, current.name)


def _build_initial_rows(zero_path: Path, fields: list[str]) -> list[_InitialFieldRow]:
    return [
        _build_initial_field_row(zero_path / field, field)
        for field in fields
    ]


def _build_initial_field_row(file_path: Path, field: str) -> _InitialFieldRow:
    try:
        value = read_entry(file_path, "internalField")
    except OpenFOAMError as exc:
        error_text = str(exc)
        return _InitialFieldRow(
            name=field,
            path=file_path,
            type_label="<error>",
            preview=_compact_preview(error_text),
            error=error_text,
        )

    validator, type_label = choose_validator("internalField", value)
    validator, type_label = detect_type_with_foamlib(
        file_path,
        "internalField",
        validator,
        type_label,
    )

    preview_text, extra_text = _format_preview(value)
    return _InitialFieldRow(
        name=field,
        path=file_path,
        type_label=type_label or "internalField",
        preview=preview_text,
        extra=extra_text,
    )


def _compact_preview(value: str | None, max_len: int = 80) -> str:
    if value is None:
        return "<empty>"
    text = " ".join(value.splitlines()).strip()
    if not text:
        return "<empty>"
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text


def _format_preview(value: str | None) -> tuple[str, str | None]:
    preview = _compact_preview(value)
    if preview.lower().startswith("uniform"):
        parts = preview.split(maxsplit=1)
        detail = parts[1] if len(parts) > 1 else ""
        return "uniform", detail or None
    return preview, None


def _draw_initial_conditions_table(
    stdscr: Any,
    rows: list[_InitialFieldRow],
    state: _InitialState,
    zero_label: str,
    status_line: str | None,
) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    title = f"Initial conditions ({zero_label})"
    with suppress(curses.error):
        stdscr.addstr(0, 0, title[: max(1, width - 1)])
    row = 1
    if status_line:
        with suppress(curses.error):
            stdscr.addstr(row, 0, status_line[: max(1, width - 1)])
        row += 1
    with suppress(curses.error):
        stdscr.addstr(row, 0, "")
    row += 1

    field_col = max(10, min(26, width // 4))
    type_col = max(8, min(18, width // 5))
    preview_col = max(10, width - field_col - type_col - 4)
    header_line = (
        "Field".ljust(field_col)
        + "Type".ljust(type_col)
        + "Preview".ljust(preview_col)
    )
    with suppress(curses.error):
        stdscr.addstr(row, 0, header_line[: max(1, width - 1)])
    start_row = row + 1
    visible_rows = max(1, height - start_row - 1)
    _adjust_initial_scroll(state, len(rows), visible_rows)
    for idx, row_data in enumerate(rows[state.scroll : state.scroll + visible_rows]):
        line_y = start_row + idx
        selected = state.scroll + idx == state.row
        attr = curses.color_pair(1) if selected else 0
        field_text = row_data.name[: field_col]
        type_text = row_data.type_label[: type_col]
        preview_text = row_data.preview[: preview_col]
        extra_limit = max(0, width - (field_col + type_col + preview_col) - 1)
        extra_text = (row_data.extra or "")[:extra_limit]
        with suppress(curses.error):
            stdscr.addstr(line_y, 0, field_text.ljust(field_col)[: field_col], attr)
            stdscr.addstr(
                line_y,
                field_col,
                type_text.ljust(type_col)[: type_col],
                attr,
            )
            stdscr.addstr(
                line_y,
                field_col + type_col,
                preview_text.ljust(preview_col)[: preview_col],
                attr,
            )
            if extra_text:
                extra_col = field_col + type_col + preview_col
                with suppress(curses.error):
                    stdscr.addstr(
                        line_y,
                        extra_col,
                        extra_text.ljust(max(0, width - extra_col)),
                        attr,
                    )

    hint = key_hint("back", "h")
    status = f"Enter: edit field  ?: help  {hint}: back"
    with suppress(curses.error):
        stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(
            height - 1,
            0,
            status[: max(1, width - 1)].ljust(max(1, width - 1)),
        )
        stdscr.attroff(curses.A_REVERSE)
    stdscr.refresh()


def _adjust_initial_scroll(state: _InitialState, total: int, visible: int) -> None:
    if total <= 0:
        state.row = 0
        state.scroll = 0
        return
    state.row = max(0, min(total - 1, state.row))
    if state.row < state.scroll:
        state.scroll = state.row
    elif state.row >= state.scroll + visible:
        state.scroll = state.row - visible + 1
    max_scroll = max(0, total - visible)
    state.scroll = max(0, min(state.scroll, max_scroll))


def _edit_initial_field(
    stdscr: Any,
    case_path: Path,
    file_path: Path,
    field: str,
) -> None:
    try:
        value = read_entry(file_path, "internalField")
    except OpenFOAMError as exc:
        _show_message(stdscr, f"Failed to read internalField: {exc}")
        return

    if field in _DERIVED_FIELDS:
        _show_message(
            stdscr,
            f"{field} is derived; editing may require updating related fields.",
        )

    validator, type_label = choose_validator("internalField", value)
    validator, type_label = detect_type_with_foamlib(
        file_path,
        "internalField",
        validator,
        type_label,
    )

    entry = Entry(key="internalField", value=value)

    def on_save(new_value: str) -> bool:
        return apply_assignment_or_write(case_path, file_path, ["internalField"], new_value)

    editor = EntryEditor(
        stdscr,
        entry,
        on_save,
        validator=validator,
        type_label=type_label,
        case_label=case_path.name,
    )
    editor.edit()


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    back_hint = key_hint("back", "h")
    stdscr.addstr(f"Press {back_hint} to return.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()
