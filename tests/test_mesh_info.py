from __future__ import annotations

from pathlib import Path

from ofti.core.mesh_info import boundary_summary, mesh_counts


def test_mesh_counts_reads_polymesh(tmp_path: Path) -> None:
    poly = tmp_path / "constant" / "polyMesh"
    poly.mkdir(parents=True)
    (poly / "points").write_text("// comment\n8\n(\n)\n")
    (poly / "faces").write_text("12\n(\n)\n")
    (poly / "owner").write_text("(\n0\n1\n2\n)\n")
    (poly / "neighbour").write_text("(\n0\n2\n3\n)\n")

    cells, faces, points = mesh_counts(tmp_path)
    assert cells == 4
    assert faces == 12
    assert points == 8


def test_boundary_summary_counts_types(tmp_path: Path) -> None:
    poly = tmp_path / "constant" / "polyMesh"
    poly.mkdir(parents=True)
    boundary = poly / "boundary"
    boundary.write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class polyBoundaryMesh;",
                "    location \"constant/polyMesh\";",
                "    object boundary;",
                "}",
                "2",
                "(",
                "    inlet",
                "    {",
                "        type patch;",
                "        nFaces 20;",
                "        startFace 0;",
                "    }",
                "    outlet",
                "    {",
                "        type wall;",
                "        nFaces 10;",
                "        startFace 20;",
                "    }",
                ")",
            ],
        ),
    )
    summary = boundary_summary(tmp_path)
    assert summary["patches"] == 2
    assert summary["types"]["patch"] == 1
    assert summary["types"]["wall"] == 1
