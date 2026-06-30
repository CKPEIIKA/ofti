from __future__ import annotations

from pathlib import Path

from ofti.foam.openfoam import FileCheckResult
from ofti.tools.case_doctor import _lint_case_dicts, build_case_doctor_report


def test_lint_case_dicts_downgrades_parser_like_issues(tmp_path: Path, monkeypatch) -> None:
    case_path = tmp_path / "case"
    file_path = case_path / "system" / "controlDict"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("FoamFile{}\n")

    result = FileCheckResult(
        errors=[
            "Failed to list keywords for '/x': file is not recognized as an OpenFOAM dictionary (missing/invalid FoamFile header).",
            "Failed to list keywords for '/x': parser error (something).",
            "boundaryField missing patches: outlet",
            "real hard error",
        ],
        warnings=["existing warning"],
        checked=True,
    )
    monkeypatch.setattr("ofti.tools.case_doctor._can_lint", lambda: True)
    monkeypatch.setattr("ofti.tools.case_doctor.openfoam.verify_case", lambda _case: {file_path: result})

    errors, warnings = _lint_case_dicts(case_path)

    assert len(errors) == 1
    assert "real hard error" in errors[0]
    assert any("missing/invalid FoamFile header" in item for item in warnings)
    assert any("parser error" in item for item in warnings)
    assert any("boundaryField missing patches:" in item for item in warnings)
    assert any("existing warning" in item for item in warnings)


def test_build_case_doctor_missing_zero_is_warning(tmp_path: Path, monkeypatch) -> None:
    case_path = tmp_path / "case"
    (case_path / "system").mkdir(parents=True)
    (case_path / "system" / "controlDict").write_text("application simpleFoam;\n")
    (case_path / "system" / "fvSchemes").write_text("FoamFile{}\n")
    (case_path / "system" / "fvSolution").write_text("FoamFile{}\n")
    (case_path / "constant" / "polyMesh").mkdir(parents=True)
    (case_path / "constant" / "polyMesh" / "boundary").write_text("FoamFile{}\n")
    monkeypatch.setattr("ofti.tools.case_doctor._can_lint", lambda: False)

    report = build_case_doctor_report(case_path)

    assert not any("Missing 0/ (or 0.orig)" in item for item in report["errors"])
    assert any("Missing 0/ (or 0.orig)" in item for item in report["warnings"])


def test_lint_case_dicts_suppresses_include_heavy_parser_noise(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case_path = tmp_path / "case"
    file_path = case_path / "system" / "sampleDict"
    file_path.parent.mkdir(parents=True)
    file_path.write_text('#include "custom.inc"\n')

    result = FileCheckResult(
        errors=[
            "Failed to list keywords for '/x': file is not recognized as an OpenFOAM dictionary (missing/invalid FoamFile header).",
            "Failed to list keywords for '/x': parser error (unsupported syntax).",
        ],
        warnings=[],
        checked=True,
    )
    monkeypatch.setattr("ofti.tools.case_doctor._can_lint", lambda: True)
    monkeypatch.setattr("ofti.tools.case_doctor.openfoam.verify_case", lambda _case: {file_path: result})

    errors, warnings = _lint_case_dicts(case_path)

    assert errors == []
    assert not any("parser error" in item for item in warnings)
    assert not any("missing/invalid FoamFile header" in item for item in warnings)
    assert any("parser lint skipped for include-heavy/custom syntax" in item for item in warnings)


def test_case_doctor_screen_uses_fast_report_without_parser_lint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case_path = tmp_path / "case"
    (case_path / "system").mkdir(parents=True)
    (case_path / "system" / "controlDict").write_text("application simpleFoam;\n")

    monkeypatch.setattr(
        "ofti.tools.case_doctor._lint_case_dicts",
        lambda _case: (_ for _ in ()).throw(AssertionError("lint should be skipped in TUI")),
    )
    shown: list[str] = []

    class FakeViewer:
        def __init__(self, _stdscr, text: str) -> None:
            shown.append(text)

        def display(self) -> None:
            return None

    from ofti.tools.case_doctor import case_doctor_screen

    case_doctor_screen(object(), case_path, viewer_cls=FakeViewer)

    assert shown
    assert "Syntax lint skipped in TUI" in shown[0]
