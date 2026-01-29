from __future__ import annotations

from pathlib import Path

from ofti.core.mesh_info import mesh_counts


def _write_list(path: Path, values: list[int]) -> None:
    path.write_text("\n".join([str(len(values)), "(", *[str(v) for v in values], ")"]))


def test_mesh_counts_from_poly_mesh(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    poly = case_dir / "constant" / "polyMesh"
    poly.mkdir(parents=True)

    _write_list(poly / "points", [0, 1, 2, 3])
    _write_list(poly / "faces", [0, 1, 2])
    _write_list(poly / "owner", [0, 0, 1])
    _write_list(poly / "neighbour", [1, 2, 2])

    cells, faces, points = mesh_counts(case_dir)
    assert cells == 3
    assert faces == 3
    assert points == 4
