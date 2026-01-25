from __future__ import annotations

from pathlib import Path

from ofti.core import boundary as bm


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_build_boundary_matrix_statuses(monkeypatch, tmp_path: Path) -> None:
    boundary_text = """FoamFile
{
    version 2.0;
    format ascii;
    class polyBoundaryMesh;
    location "constant/polyMesh";
    object boundary;
}
4
(
inlet
{
    type patch;
}
outlet
{
    type patch;
}
wall
{
    type wall;
}
front
{
    type symmetryPlane;
}
)
"""
    _write_text(tmp_path / "constant" / "polyMesh" / "boundary", boundary_text)
    (tmp_path / "0").mkdir()
    _write_text(tmp_path / "0" / "U", "dummy")
    _write_text(tmp_path / "0" / "p", "dummy")

    def fake_list_subkeys(file_path: Path, _entry: str) -> list[str]:
        if file_path.name == "U":
            return ["inlet", "outlet"]
        if file_path.name == "p":
            return ["outlet", ".*"]
        return []

    def fake_read_entry(file_path: Path, key: str) -> str:
        if file_path.name == "U" and "inlet" in key and key.endswith(".type"):
            return "fixedValue;"
        if file_path.name == "U" and "inlet" in key and key.endswith(".value"):
            return "uniform (1 0 0);"
        if file_path.name == "U" and "outlet" in key and key.endswith(".type"):
            return "zeroGradient;"
        if file_path.name == "p" and "outlet" in key and key.endswith(".type"):
            return "fixedValue;"
        return ""

    monkeypatch.setattr(bm, "list_subkeys", fake_list_subkeys)
    monkeypatch.setattr(bm, "read_entry", fake_read_entry)

    matrix = bm.build_boundary_matrix(tmp_path)

    assert matrix.fields == ["U", "p"]
    assert matrix.patches == ["inlet", "outlet", "wall", "front"]
    assert matrix.patch_types["wall"] == "wall"
    assert matrix.data["inlet"]["U"].status == "OK"
    assert matrix.data["wall"]["U"].status == "MISSING"
    assert matrix.data["wall"]["p"].status == "WILDCARD"
