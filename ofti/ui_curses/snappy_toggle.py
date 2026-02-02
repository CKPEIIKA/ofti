from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.entry_io import read_entry
from ofti.core.tool_dicts_service import apply_edit_plan
from ofti.foam.config import key_hint
from ofti.foam.openfoam import OpenFOAMError
from ofti.ui_curses.help import menu_hint
from ofti.ui_curses.menus import Menu
from ofti.ui_curses.viewer import Viewer


def snappy_staged_screen(stdscr: Any, case_path: Path) -> bool:
    dict_path = case_path / "system" / "snappyHexMeshDict"
    if not dict_path.is_file():
        _show_message(stdscr, "Missing system/snappyHexMeshDict.")
        return False

    toggles = {
        "castellatedMesh": _read_bool(dict_path, "castellatedMesh", default=True),
        "snap": _read_bool(dict_path, "snap", default=True),
        "addLayers": _read_bool(dict_path, "addLayers", default=False),
    }

    while True:
        labels = [
            _toggle_label("castellatedMesh", toggles["castellatedMesh"]),
            _toggle_label("snap", toggles["snap"]),
            _toggle_label("addLayers", toggles["addLayers"]),
            "Run snappyHexMesh",
            "Back",
        ]
        menu = Menu(
            stdscr,
            "snappyHexMesh staged run",
            labels,
            hint_provider=lambda idx: (
                "Toggle option."
                if idx in (0, 1, 2)
                else menu_hint("menu:snappy_staged", labels[idx])
                if 0 <= idx < len(labels)
                else ""
            ),
        )
        choice = menu.navigate()
        if choice in (-1, len(labels) - 1):
            return False
        if choice in (0, 1, 2):
            key = list(toggles.keys())[choice]
            toggles[key] = not toggles[key]
            continue
        if choice == 3:
            _apply_toggles(dict_path, toggles)
            return True


def _toggle_label(label: str, enabled: bool) -> str:
    mark = "x" if enabled else " "
    return f"[{mark}] {label}"


def _read_bool(path: Path, key: str, *, default: bool) -> bool:
    try:
        raw = read_entry(path, key)
    except OpenFOAMError:
        return default
    return str(raw).strip().lower() in {"true", "1", "yes", "on"}


def _apply_toggles(path: Path, toggles: dict[str, bool]) -> None:
    case_path = path.parent.parent
    edits: list[tuple[Path, list[str], str]] = []
    for key, enabled in toggles.items():
        value = "true" if enabled else "false"
        edits.append((path, key.split("."), value))
    apply_edit_plan(case_path, edits)


def _show_message(stdscr: Any, message: str) -> None:
    back_hint = key_hint("back", "h")
    Viewer(stdscr, f"{message}\n\nPress {back_hint} to return.").display()
