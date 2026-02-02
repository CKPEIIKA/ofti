from pathlib import Path

from ofti.core.case_report import CaseReport, collect_case_report


def _write_poly_mesh(base: Path, cells: int, faces: int, points: int) -> None:
    mesh_dir = base / "constant" / "polyMesh"
    mesh_dir.mkdir(parents=True)
    (mesh_dir / "points").write_text(f"{points}\n(\n)\n")
    (mesh_dir / "faces").write_text(f"{faces}\n(\n)\n")
    owners = "\n".join(str(i) for i in range(cells))
    (mesh_dir / "owner").write_text(f"{cells}\n(\n{owners}\n)\n")
    neighbours = "\n".join(str(max(i - 1, 0)) for i in range(cells))
    (mesh_dir / "neighbour").write_text(f"{cells}\n(\n{neighbours}\n)\n")


def _write_boundary(base: Path, patches: list[tuple[str, str]]) -> None:
    mesh_dir = base / "constant" / "polyMesh"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    contents = ["("]
    for name, patch_type in patches:
        contents.append(f"    {name}")
        contents.append("    {")
        contents.append(f"        type {patch_type};")
        contents.append("    }")
    contents.append(")")
    (mesh_dir / "boundary").write_text("\n".join(contents))


def test_collect_case_report(tmp_path: Path) -> None:
    _write_poly_mesh(tmp_path, cells=3, faces=3, points=4)
    _write_boundary(tmp_path, [("inlet", "patch"), ("outlet", "patch")])

    report = collect_case_report(tmp_path)

    assert isinstance(report, CaseReport)
    assert report.cells == 3
    assert report.faces == 3
    assert report.points == 4
    assert report.patches == 2
    assert report.patch_type_counts["patch"] == 2


def test_report_handles_missing_mesh(tmp_path: Path) -> None:
    report = collect_case_report(tmp_path)
    assert report.cells is None
    assert report.faces is None
    assert report.points is None
    assert report.patches == 0
    assert report.patch_type_counts == {}
