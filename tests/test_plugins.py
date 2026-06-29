from __future__ import annotations

from pathlib import Path

from ofti.core.command_spec import CommandSpec
from ofti.plugins import FieldPreset, ProfileMatch, builtin_registry


class FakeProfile:
    name = "fake"

    def detect(self, case_dir: Path) -> ProfileMatch:
        return ProfileMatch(confidence=1.0, reasons=(str(case_dir),))

    def fields(self, case_dir: Path) -> list[str]:
        del case_dir
        return ["rho", "T"]

    def rules(self, case_dir: Path) -> list[str]:
        del case_dir
        return ["rho:min=0", "T:min=0"]


class FakeCommand:
    def __init__(self, name: str) -> None:
        self.name = name

    def command_spec(self) -> CommandSpec:
        return CommandSpec(name=self.name, summary="Fake command", handler=self.run)

    def run(self, args: object) -> int:
        del args
        return 0


class FakeBundleHints:
    name = "fake-bundle"

    def bundle_hints(self, case_dir: Path) -> list[str]:
        return [f"bundle:{case_dir}"]


def test_plugin_registry_accepts_fake_profile_and_preset() -> None:
    registry = builtin_registry()
    registry.add_preset(FieldPreset("fake-flow", ("rho", "T"), source="test"))
    registry.add_physical_profile(FakeProfile())
    registry.add_bundle_hint_provider(FakeBundleHints())

    assert registry.presets["flow"].source == "core"
    assert registry.presets["fake-flow"].fields == ("rho", "T")
    assert registry.physical_profiles["fake"].rules(Path("case")) == ["rho:min=0", "T:min=0"]
    assert registry.bundle_hints["fake-bundle"].bundle_hints(Path("case")) == ["bundle:case"]


def test_plugin_registry_rejects_duplicate_names_loudly() -> None:
    registry = builtin_registry()

    assert registry.add_knife_command(FakeCommand("charge")) is True
    first = registry.knife_commands["charge"]
    # A second plugin claiming the same command name must not overwrite silently.
    assert registry.add_knife_command(FakeCommand("charge")) is False
    assert registry.knife_commands["charge"] is first
    assert any("duplicate knife command 'charge'" in err for err in registry.errors)

    assert registry.add_preset(FieldPreset("flow", ("p",), source="test")) is False
    assert registry.presets["flow"].source == "core"
    assert registry.add_physical_profile(FakeProfile()) is True
    assert registry.add_physical_profile(FakeProfile()) is False
