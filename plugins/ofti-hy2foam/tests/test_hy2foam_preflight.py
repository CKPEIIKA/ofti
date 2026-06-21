# ruff: noqa: INP001
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLUGIN_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SRC))

from ofti_hy2foam.preflight import preflight_payload  # noqa: E402


def _case(path: Path) -> Path:
    (path / "0").mkdir(parents=True)
    (path / "system").mkdir()
    (path / "constant").mkdir()
    return path


def _species_field(path: Path, patches: tuple[str, ...]) -> None:
    patch_blocks = "\n".join(
        f"  {patch}\n  {{\n    type zeroGradient;\n  }}" for patch in patches
    )
    path.write_text(
        "FoamFile{ version 2.0; format ascii; class volScalarField; }\n"
        "internalField uniform 0.5;\n"
        f"boundaryField\n{{\n{patch_blocks}\n}}\n",
        encoding="utf-8",
    )


def test_preflight_detects_missing_fields_and_duplicate_function_objects(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    (case / "0" / "Tt").write_text("placeholder\n", encoding="utf-8")
    (case / "system" / "controlDict").write_text(
        "application hy2Foam;\n"
        "functions\n{\n"
        "  probes { type probes; }\n"
        "  probes { type probes; }\n"
        "}\n",
        encoding="utf-8",
    )

    payload = preflight_payload(case, time_name="0")

    checks = {item["name"]: item for item in payload["checks"]}
    assert payload["ok"] is False
    assert checks["hystrath_libs"]["status"] == "PASS"
    assert checks["required_fields"]["status"] == "FAIL"
    assert checks["duplicate_function_objects"]["detail"] == "probes"


def test_preflight_checks_species_patches_and_turbulence(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    (case / "constant" / "polyMesh").mkdir()
    (case / "constant" / "polyMesh" / "boundary").write_text(
        "2\n(\ninlet\n{\n type patch;\n}\nwall\n{\n type wall;\n}\n)\n",
        encoding="utf-8",
    )
    (case / "constant" / "turbulenceProperties").write_text(
        "simulationType RAS;\n",
        encoding="utf-8",
    )
    for name in ("Tt", "Tv", "p", "U"):
        (case / "0" / name).write_text("placeholder\n", encoding="utf-8")
    _species_field(case / "0" / "N2", ("inlet", "wall"))
    _species_field(case / "0" / "O2", ("inlet",))

    payload = preflight_payload(case, time_name="0")

    checks = {item["name"]: item for item in payload["checks"]}
    assert payload["ok"] is False
    assert checks["species_patch_consistency"]["status"] == "FAIL"
    assert "O2:missing=wall" in checks["species_patch_consistency"]["detail"]
    assert checks["turbulence_consistency"]["detail"] == "RAS selected but RASProperties missing"


@pytest.mark.parametrize(
    ("version", "status"),
    [
        ("v2512", "PASS"),
        ("2512", "PASS"),
        ("v2406", "WARN"),
    ],
)
def test_preflight_openfoam_version_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    status: str,
) -> None:
    case = _case(tmp_path / "case")
    monkeypatch.setenv("WM_PROJECT_VERSION", version)

    payload = preflight_payload(case, time_name="0")

    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["openfoam_version"]["status"] == status
    assert version in checks["openfoam_version"]["detail"]


def test_preflight_openfoam_version_unset_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path / "case")
    monkeypatch.delenv("WM_PROJECT_VERSION", raising=False)

    payload = preflight_payload(case, time_name="0")

    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["openfoam_version"]["status"] == "WARN"
    assert "not set" in checks["openfoam_version"]["detail"]


def test_preflight_checks_species_order_sources(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    (case / "constant" / "thermophysicalProperties").write_text(
        "species (N2 O2 NO N O);\n",
        encoding="utf-8",
    )
    (case / "constant" / "transportProperties").write_text(
        "speciesOrder (O2 N2 NO N O);\n",  # reordered vs thermo -> stock mismatch
        encoding="utf-8",
    )
    # NN-fork ordering keys belong to hy2foam-mod; the stock check must ignore them.
    (case / "system" / "nnModel").write_text(
        "stateInputOrder (p Tt Tv NO N O O2 N2);\n",
        encoding="utf-8",
    )

    payload = preflight_payload(case, time_name="0")

    checks = {item["name"]: item for item in payload["checks"]}
    detail = checks["species_order_consistency"]["detail"]
    assert checks["species_order_consistency"]["status"] == "FAIL"
    assert "transportProperties:speciesOrder" in detail
    assert "nnModel" not in detail  # NN-fork key extracted out of the stock plugin
