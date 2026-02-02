from __future__ import annotations

from pathlib import Path

from ofti.core.case_snapshot import build_case_snapshot, write_case_snapshot


def _write_boundary(path: Path) -> None:
    path.write_text(
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
                "1",
                "(",
                "    inlet",
                "    {",
                "        type patch;",
                "        nFaces 20;",
                "        startFace 0;",
                "    }",
                ")",
            ],
        ),
    )


def _write_field(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class volScalarField;",
                "    location \"0\";",
                "    object T;",
                "}",
                "dimensions [0 0 0 0 0 0 0];",
                "internalField uniform 300;",
                "boundaryField",
                "{",
                "    inlet",
                "    {",
                "        type fixedValue;",
                "        value uniform 310;",
                "    }",
                "}",
            ],
        ),
    )


def test_case_snapshot_includes_mesh_and_fields(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    poly = case_dir / "constant" / "polyMesh"
    poly.mkdir(parents=True)
    _write_boundary(poly / "boundary")
    (case_dir / "0").mkdir()
    _write_field(case_dir / "0" / "T")

    snapshot = build_case_snapshot(case_dir)
    assert snapshot["case"]["name"] == "case"
    assert snapshot["mesh"]["boundary"]["patches"] == 1
    assert "T" in snapshot["fields"]
    assert "dimensions" in snapshot["fields"]["T"]


def test_write_case_snapshot(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    (case_dir / "constant" / "polyMesh").mkdir(parents=True)
    _write_boundary(case_dir / "constant" / "polyMesh" / "boundary")
    (case_dir / "0").mkdir()
    _write_field(case_dir / "0" / "T")

    output = write_case_snapshot(case_dir)
    assert output.is_file()
    assert "case_snapshot.json" in output.name
