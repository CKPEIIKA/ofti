from __future__ import annotations

from pathlib import Path
from typing import TextIO, TypedDict

from ofti.foamlib import adapter as foamlib_integration


class BoundarySummary(TypedDict):
    patches: int
    types: dict[str, int]


def mesh_counts(case_path: Path) -> tuple[int | None, int | None, int | None]:
    """Return (cells, faces, points) from polyMesh files, or Nones if missing.
    """
    poly = case_path / "constant" / "polyMesh"
    points = _list_count(poly / "points")
    faces = _list_count(poly / "faces")
    owners = _max_index(poly / "owner")
    neighbours = _max_index(poly / "neighbour")
    cell_max = None
    if owners is not None or neighbours is not None:
        cell_max = max(val for val in (owners, neighbours) if val is not None)
    cells = cell_max + 1 if cell_max is not None else None
    return cells, faces, points


def _list_count(path: Path) -> int | None:
    try:
        with path.open("r", errors="ignore") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                if stripped.isdigit():
                    return int(stripped)
    except OSError:
        return None
    return None


def _max_index(path: Path) -> int | None:
    try:
        with path.open("r", errors="ignore") as handle:
            max_val: int | None = None
            for stripped in _poly_mesh_data_lines(handle):
                if stripped == ")":
                    break
                max_val = _max_line_index(stripped, max_val)
            return max_val
    except OSError:
        return None


def _poly_mesh_data_lines(handle: TextIO) -> list[str]:
    in_data = False
    lines: list[str] = []
    for line in handle:
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if in_data:
            lines.append(stripped)
        elif stripped == "(":
            in_data = True
    return lines


def _max_line_index(line: str, current: int | None) -> int | None:
    max_val = current
    for token in line.replace("(", " ").replace(")", " ").split():
        if token.isdigit():
            value = int(token)
            max_val = value if max_val is None else max(max_val, value)
    return max_val


def boundary_summary(case_path: Path) -> BoundarySummary:
    boundary = case_path / "constant" / "polyMesh" / "boundary"
    if not boundary.is_file():
        return {"patches": 0, "types": {}}
    patches, patch_types = _read_boundary_file(boundary)
    type_counts: dict[str, int] = {}
    for patch in patches:
        entry_type = patch_types.get(patch, "unknown")
        type_counts[entry_type] = type_counts.get(entry_type, 0) + 1
    return {"patches": len(patches), "types": type_counts}


def _read_boundary_file(boundary: Path) -> tuple[list[str], dict[str, str]]:
    patches, patch_types = _read_boundary_with_foamlib(boundary)
    if patches:
        return patches, patch_types
    try:
        text = boundary.read_text(errors="ignore")
    except OSError:
        return [], {}
    from ofti.core.boundary import parse_boundary_text

    return parse_boundary_text(text) if text else ([], {})


def _read_boundary_with_foamlib(boundary: Path) -> tuple[list[str], dict[str, str]]:
    if not foamlib_integration.available():
        return [], {}
    try:
        return foamlib_integration.parse_boundary_file(boundary)
    except Exception:
        return [], {}
