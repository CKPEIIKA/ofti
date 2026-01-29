from __future__ import annotations

import re
from typing import Any


def parse_vertices_text(text: str) -> list[tuple[float, float, float]]:
    vectors: list[tuple[float, float, float]] = []
    for match in re.finditer(r"\(([^()]+)\)", text):
        parts = match.group(1).split()
        if len(parts) != 3:
            continue
        try:
            x, y, z = (float(part) for part in parts)
        except ValueError:
            continue
        vectors.append((x, y, z))
    return vectors


def parse_vertices_node(node: Any) -> list[tuple[float, float, float]]:
    vectors: list[tuple[float, float, float]] = []
    if not isinstance(node, (list, tuple)):
        return vectors
    for item in node:
        if isinstance(item, (list, tuple)) and len(item) == 3:
            try:
                x, y, z = (float(val) for val in item)
            except (TypeError, ValueError):
                continue
            vectors.append((x, y, z))
    return vectors


def parse_blocks_text(text: str) -> list[tuple[str, list[int]]]:
    blocks: list[tuple[str, list[int]]] = []
    for match in re.finditer(r"(\w+)\s*\(\s*([0-9\s]+)\s*\)", text):
        block_type = match.group(1)
        indices = _parse_int_list(match.group(2))
        if len(indices) == 8:
            blocks.append((block_type, indices))
    return blocks


def parse_blocks_node(node: Any) -> list[tuple[str, list[int]]]:
    blocks: list[tuple[str, list[int]]] = []
    if not isinstance(node, (list, tuple)):
        return blocks
    for item in node:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        block_type = item[0]
        verts = item[1]
        if not isinstance(block_type, str) or not isinstance(verts, (list, tuple)):
            continue
        try:
            indices = [int(v) for v in verts]
        except (TypeError, ValueError):
            continue
        if len(indices) == 8:
            blocks.append((block_type, indices))
    return blocks


def parse_boundary_names_text(text: str) -> list[str]:
    names: list[str] = []
    in_boundary = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("boundary"):
            in_boundary = True
            continue
        if in_boundary and line.startswith("}"):
            break
        if in_boundary and line.endswith("{"):
            name = line[:-1].strip()
            if name and name not in names:
                names.append(name)
    return names


def parse_boundary_names_node(node: Any) -> list[str]:
    names: list[str] = []
    if isinstance(node, dict):
        names.extend([key for key in node if isinstance(key, str)])
    if isinstance(node, (list, tuple)):
        names.extend(
            [
                item[0]
                for item in node
                if isinstance(item, (list, tuple)) and item and isinstance(item[0], str)
            ],
        )
    return names


def _parse_int_list(text: str) -> list[int]:
    values: list[int] = []
    for token in text.split():
        try:
            values.append(int(token))
        except ValueError:
            continue
    return values
