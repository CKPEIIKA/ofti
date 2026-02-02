from __future__ import annotations

from pathlib import Path

import pytest

from ofti.core.boundary import change_patch_type, rename_boundary_patch
from ofti.foamlib import adapter as foamlib_integration


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required for boundary action tests",
)
def test_rename_boundary_patch_updates_fields(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    poly = case_dir / "constant" / "polyMesh"
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
    field = case_dir / "0" / "U"
    field.parent.mkdir(parents=True)
    field.write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class volVectorField;",
                "    location \"0\";",
                "    object U;",
                "}",
                "boundaryField",
                "{",
                "    inlet",
                "    {",
                "        type fixedValue;",
                "        value uniform (1 0 0);",
                "    }",
                "}",
            ],
        ),
    )

    ok, message = rename_boundary_patch(case_dir, "inlet", "inflow")
    assert ok, message
    text = field.read_text()
    assert "inflow" in text
    assert "inlet" not in text


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required for boundary action tests",
)
def test_change_patch_type_updates_boundary(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    poly = case_dir / "constant" / "polyMesh"
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
                "1",
                "(",
                "    outlet",
                "    {",
                "        type patch;",
                "        nFaces 20;",
                "        startFace 0;",
                "    }",
                ")",
            ],
        ),
    )

    ok, message = change_patch_type(case_dir, "outlet", "wall")
    assert ok, message
    assert "type wall" in boundary.read_text()
