from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from ofti.core.times import latest_time
from ofti.foamlib import adapter as foamlib_integration
from ofti.tools.runner import _show_message
from ofti.ui_curses.help import menu_hint
from ofti.ui_curses.menus import Menu
from ofti.ui_curses.viewer import Viewer


def field_summary_screen(stdscr: Any, case_path: Path) -> None:
    time_dir = _latest_time_dir(case_path)
    if time_dir is None:
        _show_message(stdscr, "No time directories found in case.")
        return
    files = sorted(p for p in time_dir.iterdir() if p.is_file())
    if not files:
        _show_message(stdscr, f"No field files found in {time_dir}.")
        return
    labels = [p.name for p in files]
    menu = Menu(
        stdscr,
        f"Select field ({time_dir.name})",
        [*labels, "Back"],
        hint_provider=lambda idx: (
            "Select field file for summary."
            if 0 <= idx < len(labels)
            else menu_hint("menu:field_select", "Back")
        ),
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return
    path = files[choice]
    lines = _field_summary_lines(case_path, path)
    Viewer(stdscr, "\n".join(lines)).display()


def _latest_time_dir(case_path: Path) -> Path | None:
    latest = latest_time(case_path)
    if not latest:
        return None
    time_dir = case_path / latest
    if time_dir.is_dir():
        return time_dir
    return None


def _field_summary_lines(case_path: Path, field_path: Path) -> list[str]:
    rel = field_path.relative_to(case_path).as_posix()
    lines = ["FIELD SUMMARY", "", f"File: {rel}", ""]
    if not (foamlib_integration.available() and foamlib_integration.is_foam_file(field_path)):
        lines.append("foamlib not available or file not recognized.")
        return lines
    try:
        klass = foamlib_integration.read_entry_node(field_path, "FoamFile.class")
    except Exception:
        klass = None
    try:
        obj = foamlib_integration.read_entry_node(field_path, "FoamFile.object")
    except Exception:
        obj = None
    if klass:
        lines.append(f"Class: {klass}")
    if obj:
        lines.append(f"Object: {obj}")
    lines.append("")

    internal = _read_optional_node(field_path, "internalField")
    lines.extend(_summarize_internal_field(internal))

    patches = foamlib_integration.list_subkeys(field_path, "boundaryField")
    if patches:
        lines.append(f"Boundary patches: {len(patches)}")
    else:
        lines.append("Boundary patches: none")
    return lines


def _read_optional_node(field_path: Path, key: str) -> object | None:
    try:
        return foamlib_integration.read_entry_node(field_path, key)
    except Exception:
        return None


def _summarize_internal_field(node: object | None) -> list[str]:  # noqa: PLR0911
    if node is None:
        return ["Internal field: <missing>"]
    if isinstance(node, (int, float, bool)):
        return [f"Internal field: {node}"]
    if isinstance(node, str):
        return [f"Internal field: {node.strip()}"]
    if isinstance(node, (list, tuple)):
        return _summarize_sequence(cast(list[object] | tuple[object, ...], node))
    if hasattr(node, "shape"):
        try:
            size = int(getattr(node, "size", 0))
            if size <= 0:
                return [f"Internal field: array shape={getattr(node, 'shape', '')}"]
            return _summarize_array(node)
        except Exception:
            return [f"Internal field: array shape={getattr(node, 'shape', '')}"]
    return [f"Internal field: {type(node).__name__}"]


def _summarize_sequence(values: list[object] | tuple[object, ...]) -> list[str]:
    floats: list[float] = []
    for value in values:
        if isinstance(value, (int, float)):
            floats.append(float(value))
            continue
        with suppress(Exception):
            floats.append(float(str(value)))
    if not floats:
        return [f"Internal field: list ({len(values)})"]
    return [f"Internal field: vector {floats}"]


def _summarize_array(node: object) -> list[str]:
    astype = getattr(node, "astype", None)
    if not callable(astype):
        return [f"Internal field: array shape={getattr(node, 'shape', '')}"]
    try:
        values = astype(float)
    except Exception:
        return [f"Internal field: array shape={getattr(node, 'shape', '')}"]
    min_fn = getattr(values, "min", None)
    max_fn = getattr(values, "max", None)
    if not callable(min_fn) or not callable(max_fn):
        return [f"Internal field: array shape={getattr(values, 'shape', '')}"]
    try:
        min_val = float(min_fn())
        max_val = float(max_fn())
    except Exception:
        return [f"Internal field: array shape={getattr(values, 'shape', '')}"]
    shape = getattr(values, "shape", "")
    return [f"Internal field: array shape={shape} min={min_val:.6g} max={max_val:.6g}"]
