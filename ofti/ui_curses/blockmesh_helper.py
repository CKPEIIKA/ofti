from __future__ import annotations

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
from ofti.ui_curses.viewer import Viewer


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
        lines += ["", "Blocks (type: indices)"]
        for idx, (block_type, indices) in enumerate(blocks):
            lines.append(f"{idx:>3}: {block_type} ({' '.join(str(i) for i in indices)})")

    if boundaries:
        lines += ["", "Boundary patches"]
        for name in boundaries:
            lines.append(f"- {name}")

    lines += ["", "Tip: open Config Manager to edit blockMeshDict."]
    Viewer(stdscr, "\n".join(lines)).display()


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
