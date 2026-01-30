from __future__ import annotations

import curses
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from ofti import foamlib_adapter
from ofti.core.blockmesh import (
    parse_blocks_node,
    parse_blocks_text,
    parse_boundary_names_node,
    parse_boundary_names_text,
    parse_vertices_node,
    parse_vertices_text,
)
from ofti.core.entry_io import read_entry
from ofti.core.versioning import get_dict_path
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import OpenFOAMError
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
from ofti.ui_curses.inputs import prompt_input


def blockmesh_helper_screen(stdscr: Any, case_path: Path) -> None:
    dict_rel = get_dict_path("blockMeshDict")
    dict_path = case_path / dict_rel
    if not dict_path.is_file():
        _show_message(stdscr, f"Missing {dict_rel}.")
        return

    vertices, blocks, boundaries, edges = _load_blockmesh_details(dict_path)
    if not vertices:
        _show_message(stdscr, "No vertices found in blockMeshDict.")
        return

    summary = (
        f"Vertices: {len(vertices)} | Blocks: {len(blocks)} | "
        f"Boundaries: {len(boundaries)} | Edges: {edges}"
    )
    lines = [
        "blockMesh overview",
        "",
        summary,
        "",
        "Vertices (index: x y z)",
    ]
    for idx, (x, y, z) in enumerate(vertices):
        lines.append(f"{idx:>3}: {x:.6g} {y:.6g} {z:.6g}")

    if blocks:
        lines += ["", "Blocks (type: indices -> vertices)"]
        for idx, (block_type, indices) in enumerate(blocks):
            indices_text = " ".join(str(i) for i in indices)
            lines.append(f"{idx:>3}: {block_type} ({indices_text})")
            for vid in indices:
                if 0 <= vid < len(vertices):
                    x, y, z = vertices[vid]
                    lines.append(f"      v{vid}: {x:.6g} {y:.6g} {z:.6g}")

    if boundaries:
        lines += ["", "Boundary patches"]
        for name in boundaries:
            lines.append(f"- {name}")

    lines += ["", "Press e to open blockMeshDict in $EDITOR."]
    _blockmesh_viewer(stdscr, lines, dict_path)


def _blockmesh_viewer(
    stdscr: Any,
    lines: list[str],
    dict_path: Path,
) -> None:
    start_line = 0
    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        back_hint = key_hint("back", "h")
        header = f"Press {back_hint} or Enter to exit, e to edit, / to search."
        with suppress(curses.error):
            stdscr.addstr(header[: max(1, width - 1)] + "\n\n")
        end_line = start_line + height - 3
        for line in lines[start_line:end_line]:
            text = line[: max(1, width - 1)]
            try:
                stdscr.addstr(text + "\n")
            except curses.error:
                break
        stdscr.refresh()
        key = stdscr.getch()
        if key_in(key, get_config().keys.get("quit", [])):
            return
        if key == ord("e"):
            _open_file_in_editor(stdscr, dict_path)
            continue
        if key == ord("/") or key_in(key, get_config().keys.get("search", [])):
            start_line = _blockmesh_search(stdscr, lines, start_line)
            continue
        if key == curses.KEY_RESIZE:
            continue
        if key in (10, 13) or key_in(key, get_config().keys.get("back", [])):
            return
        start_line = _blockmesh_nav(start_line, key, end_line, height, len(lines))


def _blockmesh_search(stdscr: Any, lines: list[str], start_line: int) -> int:
    stdscr.clear()
    query = prompt_input(stdscr, "Search: ")
    if query is None:
        return start_line
    query = query.strip()
    if not query:
        return start_line
    for i in range(start_line + 1, len(lines)):
        if query in lines[i]:
            return i
    return start_line


def _blockmesh_nav(
    start_line: int,
    key: int,
    end_line: int,
    height: int,
    total: int,
) -> int:
    cfg = get_config()
    if key_in(key, cfg.keys.get("top", [])):
        return 0
    if key_in(key, cfg.keys.get("bottom", [])):
        return max(0, total - (height - 3))
    if (key in (curses.KEY_DOWN,) or key_in(key, cfg.keys.get("down", []))) and end_line < total:
        return start_line + 1
    if (key in (curses.KEY_UP,) or key_in(key, cfg.keys.get("up", []))) and start_line > 0:
        return start_line - 1
    return start_line


def _open_file_in_editor(stdscr: Any, file_path: Path) -> None:
    editor = os.environ.get("EDITOR") or "vi"
    curses.endwin()
    try:
        resolved = resolve_executable(editor)
        run_trusted([resolved, str(file_path)], capture_output=False, check=False)
    except OSError as exc:
        _show_message(stdscr, f"Failed to run {editor}: {exc}")
    finally:
        stdscr.clear()
        stdscr.refresh()


def _load_blockmesh_details(
    path: Path,
) -> tuple[list[tuple[float, float, float]], list[tuple[str, list[int]]], list[str], int]:
    if foamlib_adapter.available() and foamlib_adapter.is_foam_file(path):
        return _load_blockmesh_details_foamlib(path)
    return _load_blockmesh_details_text(path)


def _load_blockmesh_details_foamlib(
    path: Path,
) -> tuple[list[tuple[float, float, float]], list[tuple[str, list[int]]], list[str], int]:
    try:
        node = foamlib_adapter.read_entry_node(path, "vertices")
    except Exception:
        node = None
    vertices = parse_vertices_node(node) if node is not None else []
    try:
        blocks_node = foamlib_adapter.read_entry_node(path, "blocks")
    except Exception:
        blocks_node = None
    blocks = parse_blocks_node(blocks_node)
    try:
        boundary_node = foamlib_adapter.read_entry_node(path, "boundary")
    except Exception:
        boundary_node = None
    boundaries = parse_boundary_names_node(boundary_node)
    try:
        edges_node = foamlib_adapter.read_entry_node(path, "edges")
    except Exception:
        edges_node = None
    edges = len(edges_node) if isinstance(edges_node, (list, tuple)) else 0
    return vertices, blocks, boundaries, edges


def _load_blockmesh_details_text(
    path: Path,
) -> tuple[list[tuple[float, float, float]], list[tuple[str, list[int]]], list[str], int]:
    try:
        text = read_entry(path, "vertices")
    except OpenFOAMError:
        return [], [], [], 0
    vertices = parse_vertices_text(text)
    try:
        blocks_text = read_entry(path, "blocks")
    except OpenFOAMError:
        blocks_text = ""
    blocks = parse_blocks_text(blocks_text)
    try:
        boundary_text = read_entry(path, "boundary")
    except OpenFOAMError:
        boundary_text = ""
    boundaries = parse_boundary_names_text(boundary_text)
    try:
        edges_text = read_entry(path, "edges")
    except OpenFOAMError:
        edges_text = ""
    edges = edges_text.count("(") if edges_text else 0
    return vertices, blocks, boundaries, edges


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    back_hint = key_hint("back", "h")
    stdscr.addstr(f"Press {back_hint} to return.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()
