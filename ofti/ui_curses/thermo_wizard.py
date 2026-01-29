from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ofti.core.entries import Entry, autoformat_value
from ofti.core.entry_io import read_entry, write_entry
from ofti.core.versioning import get_dict_path
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import OpenFOAMError
from ofti.ui_curses.entry_editor import EntryEditor
from ofti.ui_curses.menus import Menu


def thermophysical_wizard_screen(stdscr: Any, case_path: Path) -> None:
    dict_rel = get_dict_path("thermophysical")
    dict_path = case_path / dict_rel
    if not dict_path.is_file():
        _show_message(stdscr, f"Missing {dict_rel}.")
        return

    keys = ["thermoType", "mixture", "transport", "equationOfState"]
    values = {key: _read_value(dict_path, key) for key in keys}

    while True:
        labels = [_label_for(key, values[key]) for key in keys] + ["Back"]
        menu = Menu(
            stdscr,
            "Thermophysical properties wizard",
            labels,
            status_line="Edit core thermophysical slots",
        )
        choice = menu.navigate()
        if choice in (-1, len(labels) - 1):
            return

        key = keys[choice]
        entry = Entry(key=key, value=values[key])
        editor = EntryEditor(
            stdscr,
            entry,
            on_save=lambda value, k=key: _write_value(dict_path, k, value),
            validator=_thermo_validator,
            type_label="dict",
        )
        editor.edit()
        values[key] = entry.value


def _label_for(key: str, value: str) -> str:
    summary = "missing" if not value.strip() else value.splitlines()[0][:40]
    return f"{key}: {summary}"


def _read_value(path: Path, key: str) -> str:
    try:
        return read_entry(path, key)
    except OpenFOAMError:
        return ""


def _write_value(path: Path, key: str, value: str) -> bool:
    cleaned = autoformat_value(value)
    if not cleaned.strip():
        return False
    return write_entry(path, key, cleaned)


def _thermo_validator(value: str) -> str | None:
    if not value.strip():
        return "Value cannot be empty."
    lowered = value.lower()
    if "janaf" in lowered or "coeffs" in lowered:
        numbers = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", value)
        if len(numbers) < 7:
            return "Janaf/coeffs section looks too short (expected >= 7 numbers)."
    return None


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    back_hint = key_hint("back", "h")
    stdscr.addstr(f"Press {back_hint} to return.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()
