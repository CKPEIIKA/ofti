from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from ofti.core import field_diagnostics as diag
from ofti.core import field_io


def _make_case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "0").mkdir()
    (path / "system" / "controlDict").write_text("application simpleFoam;\n")
    return path


def _write_scalar(path: Path, values: Sequence[float] | float) -> None:
    if isinstance(values, (int, float)):
        internal = f"uniform {values}"
    else:
        body = "\n".join(f"{value:g}" for value in values)
        internal = f"nonuniform List<scalar>\n{len(values)}\n(\n{body}\n)"
    path.write_text(
        "FoamFile{ version 2.0; format ascii; class volScalarField; }\n"
        f"internalField {internal};\n"
        "boundaryField{}\n",
        encoding="utf-8",
    )


def _write_vector(path: Path, values: list[tuple[float, float, float]]) -> None:
    body = "\n".join(f"({x:g} {y:g} {z:g})" for x, y, z in values)
    path.write_text(
        "FoamFile{ version 2.0; format ascii; class volVectorField; }\n"
        f"internalField nonuniform List<vector>\n{len(values)}\n(\n{body}\n);\n"
        "boundaryField{}\n",
        encoding="utf-8",
    )


def test_resolve_latest_and_field_names(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(diag.foamlib_integration, "available", lambda: False)
    case = _make_case(tmp_path / "case")
    _write_scalar(case / "0" / "p", 1.0)
    monkeypatch.setattr(field_io, "latest_time", lambda _case: "0")

    assert diag.resolve_time_dir(case, "latest") == case / "0"
    assert diag.resolve_field_names(case / "0", None) == ["p"]
    assert diag.resolve_field_names(case / "0", ["p", "p"], preset="flow") == ["p", "U", "rho", "T"]
    assert diag.split_field_list(["p,T", "rho"]) == ["p", "T", "rho"]
    assert diag.split_field_list(None) is None

    try:
        diag.resolve_field_names(case / "0", None, preset="plugin-preset")
    except ValueError as exc:
        assert "unknown field preset" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected unknown preset error")


def test_read_internal_field_error_branches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(diag.foamlib_integration, "available", lambda: False)
    case = _make_case(tmp_path / "case")
    (case / "0" / "bad").write_text(
        "FoamFile{ class volScalarField; }\ninternalField uniform nope;\n",
        encoding="utf-8",
    )
    (case / "0" / "mismatch").write_text(
        "FoamFile{ class volScalarField; }\n"
        "internalField nonuniform List<scalar>\n2\n(\n1\n);\n",
        encoding="utf-8",
    )
    (case / "0" / "missingInternal").write_text("FoamFile{ class volScalarField; }\n")

    for name, expected in [
        ("absent", "field not found"),
        ("bad", "no numeric values"),
        ("mismatch", "count mismatch"),
        ("missingInternal", "unsupported or missing"),
    ]:
        try:
            diag.read_internal_field(case / "0" / name)
        except ValueError as exc:
            assert expected in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"expected read error for {name}")


def test_foamlib_node_coercion_and_scalar_list_fallback(tmp_path: Path, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    vector = case / "0" / "U"
    _write_vector(vector, [(1.0, 2.0, 3.0)])
    scalar = case / "0" / "p"
    _write_scalar(scalar, [1.0, 2.0, 3.0])
    monkeypatch.setattr(diag.foamlib_integration, "available", lambda: True)
    monkeypatch.setattr(diag.foamlib_integration, "is_field_file", lambda _path: True)
    monkeypatch.setattr(diag.foamlib_integration, "read_field_entry_node", lambda *_a: [1.0, 2.0, 3.0])

    assert diag.read_internal_field(vector).uniform is True
    parsed_scalar = diag.read_internal_field(scalar)
    assert parsed_scalar.uniform is False
    assert parsed_scalar.count == 3


def test_field_physical_payload_reports_violations_without_hard_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(diag.foamlib_integration, "available", lambda: False)
    case = _make_case(tmp_path / "case")
    _write_scalar(case / "0" / "rho", [1.0, -0.2, 2.0])
    _write_scalar(case / "0" / "alpha.water", [0.2, 1.2, 0.5])

    payload = diag.field_sanity_payload(case, time_name="0", fields=["rho", "alpha.water"])

    assert payload["ok"] is True
    assert payload["physical_ok"] is False
    assert payload["violations"][0]["field"] == "rho"


def test_field_physical_payload_marks_nonfinite_as_hard_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(diag.foamlib_integration, "available", lambda: False)
    case = _make_case(tmp_path / "case")
    _write_scalar(case / "0" / "p", [1.0, float("nan")])

    payload = diag.field_sanity_payload(case, time_name="0", fields=["p"])

    assert payload["ok"] is False
    assert payload["fields"][0]["nonfinite_count"] == 1
    assert payload["hard_errors"] == ["p: nonfinite values=1"]


def test_compare_fields_handles_uniform_vs_nonuniform_and_vectors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(diag.foamlib_integration, "available", lambda: False)
    left = _make_case(tmp_path / "left")
    right = _make_case(tmp_path / "right")
    _write_scalar(left / "0" / "p", 1.0)
    _write_scalar(right / "0" / "p", [1.0, 1.5])
    _write_vector(left / "0" / "U", [(1.0, 0.0, 0.0)])
    _write_vector(right / "0" / "U", [(1.0, 0.0, 0.0)])

    payload = diag.compare_fields_payload(left, right, time_name="0", fields=["p", "U"])

    rows = {row["field"]: row for row in payload["fields"]}
    assert payload["ok"] is True
    assert payload["same"] is False
    assert rows["p"]["max_abs"] == 0.5
    assert rows["p"]["max_rel"] == 1 / 3
    assert rows["U"]["max_abs"] == 0.0


def test_compare_fields_reports_count_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(diag.foamlib_integration, "available", lambda: False)
    left = _make_case(tmp_path / "left")
    right = _make_case(tmp_path / "right")
    _write_scalar(left / "0" / "p", [1.0, 2.0])
    _write_scalar(right / "0" / "p", [1.0, 2.0, 3.0])

    payload = diag.compare_fields_payload(left, right, time_name="0", fields=["p"])

    assert payload["ok"] is False
    assert "field count mismatch" in payload["errors"][0]


def test_compare_fields_reports_component_mismatch_and_nonfinite_pairs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(diag.foamlib_integration, "available", lambda: False)
    left = _make_case(tmp_path / "left")
    right = _make_case(tmp_path / "right")
    _write_vector(left / "0" / "U", [(1.0, float("inf"), 0.0)])
    (right / "0" / "U").write_text(
        "FoamFile{ class volVectorField; }\n"
        "internalField nonuniform List<vector>\n1\n(\n(1 2)\n);\n"
        "boundaryField{}\n",
        encoding="utf-8",
    )
    _write_vector(left / "0" / "V", [(1.0, float("inf"), 0.0)])
    _write_vector(right / "0" / "V", [(1.0, 2.0, 0.0)])

    mismatch = diag.compare_fields_payload(left, right, time_name="0", fields=["U"])
    nonfinite = diag.compare_fields_payload(left, right, time_name="0", fields=["V"])

    assert mismatch["ok"] is False
    assert "component mismatch" in mismatch["errors"][0]
    assert nonfinite["ok"] is True
    assert nonfinite["fields"][0]["nonfinite_pairs"] == 1


def _write_scalar_with_patch(path: Path, internal: Sequence[float] | float, patch_value: float) -> None:
    if isinstance(internal, (int, float)):
        internal_text = f"uniform {internal}"
    else:
        body = "\n".join(f"{value:g}" for value in internal)
        internal_text = f"nonuniform List<scalar>\n{len(internal)}\n(\n{body}\n)"
    path.write_text(
        "FoamFile{ version 2.0; format ascii; class volScalarField; }\n"
        f"internalField {internal_text};\n"
        "boundaryField\n"
        "{\n"
        "    outlet\n"
        "    {\n"
        "        type fixedValue;\n"
        f"        value uniform {patch_value};\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )


def test_physical_custom_rules_and_reports_on_real_files(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    _write_scalar(case / "0" / "rho", [1.0, -0.1, 2.0])
    _write_scalar(case / "0" / "T", [200.0, 300.0, 400.0])
    out = tmp_path / "physical-out"

    payload = diag.field_sanity_payload(
        case,
        time_name="0",
        rules=diag.parse_field_rules(["rho:min=0", "T:min=250,max=1000"]),
    )
    outputs = diag.write_physical_report(payload, out)

    assert payload["physical_ok"] is False
    assert {row["field"] for row in payload["violations"]} == {"rho", "T"}
    assert Path(outputs["csv"]).is_file()
    assert Path(outputs["markdown"]).read_text(encoding="utf-8").startswith("# Physical Checks")


def test_compare_fields_reference_candidate_times_patch_and_reports(tmp_path: Path) -> None:
    left = _make_case(tmp_path / "left")
    right = _make_case(tmp_path / "right")
    (left / "1").mkdir()
    (right / "2").mkdir()
    _write_scalar_with_patch(left / "1" / "p", [1.0, 2.0], 10.0)
    _write_scalar_with_patch(right / "2" / "p", [1.0, 2.5], 11.0)
    out = tmp_path / "compare-out"

    payload = diag.compare_fields_payload(
        left,
        right,
        time_name="latest",
        reference_time="1",
        candidate_time="2",
        fields=["p"],
        patch="outlet",
        rel_tol=1e-9,
    )
    outputs = diag.write_compare_report(payload, out)

    assert payload["ok"] is True
    assert payload["same"] is False
    assert payload["fields"][0]["abs_linf"] == pytest.approx(1.0)
    assert payload["fields"][0]["rel_l2"] > 0
    assert Path(outputs["csv"]).read_text(encoding="utf-8").splitlines()[0].startswith("field,")
    assert "Field Compare" in Path(outputs["markdown"]).read_text(encoding="utf-8")
