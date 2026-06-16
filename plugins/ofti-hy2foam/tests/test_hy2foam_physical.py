# ruff: noqa: INP001
from __future__ import annotations

import math
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

PLUGIN_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SRC))

from ofti_hy2foam.physical import (  # noqa: E402
    Hy2FoamPhysicalProfile,
    physical_diagnostics_payload,
    species_sum_diagnostic,
    two_temperature_diagnostic,
)


def _case(path: Path) -> Path:
    (path / "0").mkdir(parents=True)
    return path


def _scalar(
    path: Path,
    values: Sequence[float] | float,
    *,
    boundary: str = "boundaryField{}\n",
) -> None:
    if isinstance(values, float | int):
        internal = f"uniform {values}"
    else:
        body = "\n".join(f"{value:g}" for value in values)
        internal = f"nonuniform List<scalar>\n{len(values)}\n(\n{body}\n)"
    path.write_text(
        "FoamFile{ version 2.0; format ascii; class volScalarField; }\n"
        f"internalField {internal};\n"
        + boundary,
        encoding="utf-8",
    )


def test_species_sum_diagnostic_reports_deviation(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    _scalar(case / "0" / "N2", [0.7, 0.7])
    _scalar(case / "0" / "O2", [0.2, 0.1])

    payload = species_sum_diagnostic(case / "0", ("N2", "O2"))

    assert payload["checked"] is True
    assert payload["max_abs_deviation"] == pytest.approx(0.2)


def test_two_temperature_diagnostic_flags_bad_ratio(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    _scalar(case / "0" / "Tt", [1000.0, 1000.0])
    _scalar(case / "0" / "Tv", [1.0, 100.0])

    payload = two_temperature_diagnostic(case / "0", tv_tt_min=0.02, tv_tt_max=10.0)

    assert payload["checked"] is True
    assert payload["ok"] is False
    assert payload["bad_count"] == 1


def test_physical_payload_collects_transport_and_core_violations(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    _scalar(case / "0" / "rho", [1.0, -1.0])
    _scalar(case / "0" / "Tt", [1000.0, 1000.0])
    _scalar(case / "0" / "Tv", [1.0, 100.0])
    _scalar(case / "0" / "Dmix_N2", [math.nan, 1.0])

    payload = physical_diagnostics_payload(case, time_name="0", species=("N2", "O2"))

    kinds = {item["kind"] for item in payload["violations"]}
    assert payload["ok"] is True
    assert payload["physical_ok"] is False
    assert "min>=0" in kinds
    assert "nonfinite" in kinds
    assert "two_temperature_ratio" in kinds


def test_signed_flux_negative_is_not_a_violation(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    _scalar(case / "0" / "Tt", [1000.0, 1000.0])
    _scalar(case / "0" / "Tv", [1000.0, 1000.0])
    # Diffusion flux and heat fluxes are signed; negative values are physical.
    _scalar(case / "0" / "J_N2", [-3.0, 2.0])
    _scalar(case / "0" / "qDiff", [-50.0, 10.0])
    _scalar(case / "0" / "wallHeatFlux", [-1000.0, 0.0])

    payload = physical_diagnostics_payload(case, time_name="0", species=("N2", "O2"))

    assert payload["physical_ok"] is True
    assert payload["violations"] == []


def test_species_mass_fraction_above_one_is_flagged(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    _scalar(case / "0" / "N2", [0.5, 1.4])

    payload = physical_diagnostics_payload(case, time_name="0", species=("N2",))

    fraction = [item for item in payload["violations"] if item["kind"] == "fraction"]
    assert fraction and fraction[0]["field"] == "N2"
    assert payload["physical_ok"] is False


def test_profile_rules_classify_signed_and_fraction_fields(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    for name in ("Tt", "Tv", "p", "rho", "e", "ev", "Tov", "N2", "Dmix_N2", "J_N2", "qDiff"):
        _scalar(case / "0" / name, [1.0])

    rules = set(Hy2FoamPhysicalProfile().rules(case))

    assert "rho:min=0" in rules
    assert "Dmix_N2:min=0" in rules
    assert "N2:min=0,max=1" in rules
    assert "J_N2" in rules  # signed: finiteness only
    assert "qDiff" in rules


def test_profile_diagnostics_reports_species_sum_and_two_temperature(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    _scalar(case / "0" / "Tt", [1000.0, 1000.0])
    _scalar(case / "0" / "Tv", [1.0, 100.0])  # Tv/Tt = 0.001 -> below 0.02 floor
    _scalar(case / "0" / "N2", [0.7, 0.7])
    _scalar(case / "0" / "O2", [0.2, 0.1])  # sums to 0.9/0.8, deviates from 1

    diagnostics = Hy2FoamPhysicalProfile().diagnostics(case, time_name="0")

    assert diagnostics["species_sum"]["checked"] is True
    assert diagnostics["two_temperature"]["checked"] is True
    kinds = {item["kind"] for item in diagnostics["violations"]}
    assert "species_sum" in kinds
    assert "two_temperature_ratio" in kinds


def test_physical_payload_reports_patch_ranges(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    boundary = (
        "boundaryField\n{\n"
        "  wall\n  {\n    type fixedValue;\n    value uniform 1200;\n  }\n"
        "}\n"
    )
    _scalar(case / "0" / "Tt", [1000.0], boundary=boundary)
    _scalar(case / "0" / "Tv", [1000.0])

    payload = physical_diagnostics_payload(case, time_name="0", patches=("wall",))

    patches = payload["diagnostics"]["patch_ranges"]
    assert patches[0]["field"] == "Tt"
    assert patches[0]["patch"] == "wall"
    assert patches[0]["min"] == 1200.0
