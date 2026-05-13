from __future__ import annotations

from pathlib import Path

from ofti.tools.lint_service import lint_exit_code, lint_payload


def test_lint_payload_reports_pressure_decomposition_and_resource_risks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "0").mkdir()
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "constant" / "polyMesh" / "boundary").write_text("boundary")
    (case / "system" / "controlDict").write_text(
        "application simpleFoam;\nwriteControl timeStep;\nwriteInterval 10;\npurgeWrite 0;\n",
    )
    (case / "system" / "fvSchemes").write_text("FoamFile {}\n")
    (case / "system" / "fvSolution").write_text("solvers {}\n")
    (case / "system" / "decomposeParDict").write_text("numberOfSubdomains 4;\n")
    (case / "0" / "U").write_text("boundaryField {}\n")
    (case / "0" / "p").write_text("boundaryField { walls { type zeroGradient; } }\n")
    (case / "processor0").mkdir()
    (case / "processor1").mkdir()
    monkeypatch.setattr("ofti.tools.case_doctor._can_lint", lambda: False)

    payload = lint_payload(case)
    text = "\n".join(str(row) for row in payload["findings"])

    assert payload["errors"] == 0
    assert payload["warnings"] >= 3
    assert "pressure-reference" in text
    assert "numberOfSubdomains=4 but processor dirs=2" in text
    assert "frequent writes without purgeWrite" in text
    assert lint_exit_code(payload) == 0


def test_lint_exit_code_fails_on_errors() -> None:
    assert lint_exit_code({"errors": 1}) == 1
