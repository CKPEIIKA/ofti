from __future__ import annotations

from pathlib import Path

from ofti.plugins import FieldPreset, ProfileMatch, builtin_registry


class FakeProfile:
    name = "fake"

    def detect(self, case_dir: Path) -> ProfileMatch:
        return ProfileMatch(confidence=1.0, reasons=(str(case_dir),))

    def fields(self, _case_dir: Path) -> list[str]:
        return ["rho", "T"]

    def rules(self, _case_dir: Path) -> list[str]:
        return ["rho:min=0", "T:min=0"]


def test_plugin_registry_accepts_fake_profile_and_preset() -> None:
    registry = builtin_registry()
    registry.add_preset(FieldPreset("fake-flow", ("rho", "T"), source="test"))
    registry.physical_profiles["fake"] = FakeProfile()

    assert registry.presets["flow"].source == "core"
    assert registry.presets["fake-flow"].fields == ("rho", "T")
    assert registry.physical_profiles["fake"].rules(Path("case")) == ["rho:min=0", "T:min=0"]
