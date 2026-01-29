from __future__ import annotations

from pathlib import Path

import pytest

from ofti import foamlib_adapter
from ofti.core.boundary import BoundaryCell, build_boundary_matrix


@pytest.mark.skipif(
    not foamlib_adapter.available(),
    reason="foamlib required for boundary matrix tests",
)
def test_build_boundary_matrix_pitzdaily() -> None:
    case_path = Path(__file__).parents[1] / "examples" / "pitzDaily"
    matrix = build_boundary_matrix(case_path)

    assert "inlet" in matrix.patches
    assert "upperWall" in matrix.patches
    assert matrix.patch_types.get("upperWall") == "wall"
    assert matrix.patch_types.get("frontAndBack") == "empty"
    assert "U" in matrix.fields

    cell = matrix.data["inlet"]["U"]
    assert isinstance(cell, BoundaryCell)
    assert cell.status == "OK"
    assert cell.bc_type == "fixedValue"
    assert cell.value


@pytest.mark.skipif(
    not foamlib_adapter.available(),
    reason="foamlib required for boundary matrix tests",
)
def test_build_boundary_matrix_missing_boundary_field(tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    boundary_path = case_path / "constant" / "polyMesh"
    zero_path = case_path / "0"
    boundary_path.mkdir(parents=True)
    zero_path.mkdir(parents=True)

    (boundary_path / "boundary").write_text(
        "FoamFile{version 2.0;format ascii;class polyBoundaryMesh;location \"constant/polyMesh\";object boundary;}\n"
        "1\n(\n"
        " inlet { type patch; nFaces 1; startFace 0; }\n"
        ")\n",
    )

    (zero_path / "U").write_text(
        "FoamFile{version 2.0;format ascii;class volVectorField;location \"0\";object U;}\n"
        "dimensions [0 1 -1 0 0 0 0];\n"
        "internalField uniform (0 0 0);\n"
        "boundaryField{ inlet{ type fixedValue; value uniform (0 0 0); } }\n",
    )
    (zero_path / "p").write_text(
        "FoamFile{version 2.0;format ascii;class volScalarField;location \"0\";object p;}\n"
        "dimensions [0 2 -2 0 0 0 0];\n"
        "internalField uniform 0;\n",
    )

    matrix = build_boundary_matrix(case_path)
    assert matrix.data["inlet"]["U"].status == "OK"
    assert matrix.data["inlet"]["p"].status == "MISSING"


@pytest.mark.skipif(
    not foamlib_adapter.available(),
    reason="foamlib required for boundary matrix tests",
)
def test_build_boundary_matrix_wildcard(tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    boundary_path = case_path / "constant" / "polyMesh"
    zero_path = case_path / "0"
    boundary_path.mkdir(parents=True)
    zero_path.mkdir(parents=True)

    (boundary_path / "boundary").write_text(
        "FoamFile{version 2.0;format ascii;class polyBoundaryMesh;location \"constant/polyMesh\";object boundary;}\n"
        "2\n(\n"
        " inlet { type patch; nFaces 1; startFace 0; }\n"
        " outlet { type patch; nFaces 1; startFace 1; }\n"
        ")\n",
    )

    (zero_path / "U").write_text(
        "FoamFile{version 2.0;format ascii;class volVectorField;location \"0\";object U;}\n"
        "dimensions [0 1 -1 0 0 0 0];\n"
        "internalField uniform (0 0 0);\n"
        "boundaryField\n"
        "{\n"
        "  \".*\"\n"
        "  {\n"
        "    type zeroGradient;\n"
        "  }\n"
        "}\n",
    )

    matrix = build_boundary_matrix(case_path)
    assert matrix.data["inlet"]["U"].status == "WILDCARD"
    assert matrix.data["outlet"]["U"].status == "WILDCARD"


@pytest.mark.skipif(
    not foamlib_adapter.available(),
    reason="foamlib required for boundary matrix tests",
)
def test_boundary_matrix_writeback(tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    boundary_path = case_path / "constant" / "polyMesh"
    zero_path = case_path / "0"
    boundary_path.mkdir(parents=True)
    zero_path.mkdir(parents=True)

    (boundary_path / "boundary").write_text(
        "FoamFile{version 2.0;format ascii;class polyBoundaryMesh;location \"constant/polyMesh\";object boundary;}\n"
        "1\n(\n"
        " inlet { type patch; nFaces 1; startFace 0; }\n"
        ")\n",
    )

    u_path = zero_path / "U"
    u_path.write_text(
        "FoamFile{version 2.0;format ascii;class volVectorField;location \"0\";object U;}\n"
        "dimensions [0 1 -1 0 0 0 0];\n"
        "internalField uniform (0 0 0);\n"
        "boundaryField\n"
        "{\n"
        "  inlet\n"
        "  {\n"
        "    type fixedValue;\n"
        "    value uniform (0 0 0);\n"
        "  }\n"
        "}\n",
    )

    matrix = build_boundary_matrix(case_path)
    cell = matrix.data["inlet"]["U"]
    assert cell.bc_type == "fixedValue"

    assert foamlib_adapter.write_entry(
        u_path, "boundaryField.inlet.type", "zeroGradient",
    )

    matrix = build_boundary_matrix(case_path)
    cell = matrix.data["inlet"]["U"]
    assert cell.status == "OK"
    assert cell.bc_type == "zeroGradient"
