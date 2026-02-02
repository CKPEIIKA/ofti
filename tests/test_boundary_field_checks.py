from pathlib import Path

import pytest

from ofti.foam.openfoam import verify_case
from ofti.foamlib import adapter as foamlib_integration


@pytest.mark.skipif(not foamlib_integration.available(), reason="foamlib required")
def test_check_boundary_field_missing_patches(tmp_path: Path) -> None:
    case_root = tmp_path
    repo_root = Path(__file__).resolve().parents[1]
    boundary_src = repo_root / "examples" / "pitzDaily" / "constant" / "polyMesh" / "boundary"
    if not boundary_src.is_file():
        pytest.skip("examples/pitzDaily not available")
    boundary_dst = case_root / "constant" / "polyMesh" / "boundary"
    boundary_dst.parent.mkdir(parents=True, exist_ok=True)
    boundary_dst.write_text(boundary_src.read_text())

    patches, _types = foamlib_integration.parse_boundary_file(boundary_dst)
    assert patches
    keep = patches[:1]

    u_path = case_root / "0" / "U"
    u_path.parent.mkdir(parents=True, exist_ok=True)
    u_path.write_text(
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
                "dimensions [0 1 -1 0 0 0 0];",
                "internalField uniform (0 0 0);",
                "boundaryField",
                "{",
                f"    {keep[0]}",
                "    {",
                "        type fixedValue;",
                "        value uniform (1 0 0);",
                "    }",
                "}",
                "",
            ],
        ),
    )

    results = verify_case(case_root)
    errors = results[u_path].errors
    assert any("boundaryField missing patches" in err for err in errors)
