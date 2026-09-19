from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ofti_hy2foam.charge import charge_payload


def _case(path: Path) -> Path:
    (path / "0").mkdir(parents=True)
    return path


def _scalar(path: Path, values: Sequence[float], *, boundary: str = "boundaryField{}\n") -> None:
    body = "\n".join(f"{value:g}" for value in values)
    path.write_text(
        "FoamFile{ version 2.0; format ascii; class volScalarField; }\n"
        f"internalField nonuniform List<scalar>\n{len(values)}\n(\n{body}\n);\n" + boundary,
        encoding="utf-8",
    )


def test_charge_payload_reports_electron_and_ion_observability(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    boundary = "boundaryField\n{\n  wall\n  {\n    type zeroGradient;\n  }\n}\n"
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "constant" / "polyMesh" / "boundary").write_text(
        "1\n(\nwall\n{\n type wall;\n nFaces 1;\n startFace 0;\n}\n)\n",
        encoding="utf-8",
    )
    _scalar(case / "0" / "rho", [1.0, 1.0])
    _scalar(case / "0" / "e-", [1e-6, 2e-6], boundary=boundary)
    _scalar(case / "0" / "N2+", [1e-6, 1e-6], boundary=boundary)

    payload = charge_payload(case, time_name="0")

    assert payload["electron_field"] == "e-"
    assert payload["charged_species"] == ["N2+", "e-"]
    assert payload["electron_number_density"]["available"] is True
    assert payload["positive_ion_number_density"]["N2+"]["available"] is True
    assert payload["charged_wall_boundary_types"][0] == {
        "field": "N2+",
        "patch": "wall",
        "type": "zeroGradient",
    }
    assert payload["warnings"]
