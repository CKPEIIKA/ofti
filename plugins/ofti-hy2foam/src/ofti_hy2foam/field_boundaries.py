from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from ofti.core.field_io import flat_values, read_field_values

_COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE_RE = re.compile(r"//.*?$", re.MULTILINE)
_BOUNDARY_RE = re.compile(r"\bboundaryField\s*\{(?P<body>.*)\}\s*$", re.DOTALL)
_TYPE_RE = re.compile(r"\btype\s+(?P<type>[^;]+);")


def field_boundary_patches(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    text = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
    boundary = _BOUNDARY_RE.search(text)
    if not boundary:
        return []
    patches: list[dict[str, str]] = []
    body = boundary.group("body")
    for name, block in _named_blocks(body):
        match = _TYPE_RE.search(block)
        patches.append({"patch": name, "type": match.group("type").strip() if match else ""})
    return patches


def patch_value_summary(path: Path, patch: str) -> dict[str, Any]:
    data = read_field_values(path, patch=patch)
    values = flat_values(data.values)
    finite = [value for value in values if math.isfinite(value)]
    return {
        "field": path.name,
        "patch": patch,
        "kind": data.kind,
        "uniform": data.uniform,
        "count": len(values),
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "nonfinite_count": len(values) - len(finite),
    }


def wall_patch_names(case_dir: Path, *, field_paths: list[Path] | None = None) -> set[str]:
    mesh_wall = _mesh_wall_patch_names(case_dir)
    if mesh_wall:
        return mesh_wall
    names: set[str] = set()
    for path in field_paths or []:
        for patch in field_boundary_patches(path):
            patch_name = patch["patch"]
            if "wall" in patch_name.lower():
                names.add(patch_name)
    return names


def mesh_patch_names(case_dir: Path) -> set[str]:
    path = case_dir / "constant" / "polyMesh" / "boundary"
    if not path.is_file():
        return set()
    text = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
    return {name for name, _block in _named_blocks(text)}


def _mesh_wall_patch_names(case_dir: Path) -> set[str]:
    path = case_dir / "constant" / "polyMesh" / "boundary"
    if not path.is_file():
        return set()
    text = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
    return {
        name
        for name, block in _named_blocks(text)
        if re.search(r"\btype\s+wall\s*;", block)
    }


def _strip_comments(text: str) -> str:
    return _COMMENT_LINE_RE.sub("", _COMMENT_BLOCK_RE.sub("", text))


def _named_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    index = 0
    while index < len(text):
        match = re.search(r"\b([A-Za-z0-9_+.-]+)\s*\{", text[index:])
        if not match:
            break
        name = match.group(1)
        open_brace = index + match.end() - 1
        close_brace = _matching_brace(text, open_brace)
        if close_brace is None:
            break
        blocks.append((name, text[open_brace + 1 : close_brace]))
        index = close_brace + 1
    return blocks


def _matching_brace(text: str, open_brace: int) -> int | None:
    depth = 0
    for index in range(open_brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None
