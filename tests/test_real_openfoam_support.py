from __future__ import annotations

from pathlib import Path

from tests.real_openfoam_support import parse_profile_specs, scenario_enabled


def test_parse_profile_specs_supports_legacy_and_extended_forms(tmp_path: Path) -> None:
    case_a = tmp_path / "case-a"
    case_b = tmp_path / "case-b"
    case_a.mkdir()
    case_b.mkdir()

    profiles = parse_profile_specs(
        f"baseline={case_a};solver=simpleFoam;tags=serial,air:{case_b}",
    )

    assert profiles[0].name == "baseline"
    assert profiles[0].source == case_a.resolve()
    assert profiles[0].solver == "simpleFoam"
    assert profiles[0].tags == frozenset({"serial", "air"})
    assert profiles[1].name == "case-b"
    assert profiles[1].source == case_b.resolve()


def test_parse_profile_specs_ignores_missing_cases(tmp_path: Path) -> None:
    assert parse_profile_specs(f"missing={tmp_path / 'none'}") == []


def test_scenario_enabled_accepts_empty_all_and_named(monkeypatch) -> None:
    monkeypatch.delenv("OFTI_REAL_SCENARIOS", raising=False)
    assert scenario_enabled("queue") is True
    monkeypatch.setenv("OFTI_REAL_SCENARIOS", "smoke,queue")
    assert scenario_enabled("queue") is True
    assert scenario_enabled("hpc") is False
    monkeypatch.setenv("OFTI_REAL_SCENARIOS", "all")
    assert scenario_enabled("hpc") is True
