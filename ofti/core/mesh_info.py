from __future__ import annotations

from pathlib import Path


def mesh_counts(case_path: Path) -> tuple[int | None, int | None, int | None]:
    """
    Return (cells, faces, points) from polyMesh files, or Nones if missing.
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
            in_data = False
            max_val: int | None = None
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                if not in_data:
                    if stripped == "(":
                        in_data = True
                    continue
                if stripped == ")":
                    break
                for token in stripped.replace("(", " ").replace(")", " ").split():
                    if token.isdigit():
                        value = int(token)
                        max_val = value if max_val is None else max(max_val, value)
            return max_val
    except OSError:
        return None
