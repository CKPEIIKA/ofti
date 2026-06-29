from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol

from ofti.core.command_spec import CommandSpec


@dataclass(frozen=True)
class FieldPreset:
    name: str
    fields: tuple[str, ...]
    description: str = ""
    source: str = "core"


@dataclass(frozen=True)
class ProfileMatch:
    confidence: float
    reasons: tuple[str, ...] = ()


class PhysicalRuleProvider(Protocol):
    name: str

    def detect(self, case_dir: Path) -> ProfileMatch: ...

    def fields(self, case_dir: Path) -> Sequence[str]: ...

    def rules(self, case_dir: Path) -> Sequence[str | Any]: ...


class SpecCommandProvider(Protocol):
    """A knife command provider: declares a framework-neutral CommandSpec.

    The CLI adapter builds argparse from the spec, so the plugin never touches
    argparse internals. ``command_spec().handler`` is the run callable.
    """

    name: str

    def command_spec(self) -> CommandSpec: ...

    def run(self, args: Any) -> int: ...


#: A knife command declares a framework-neutral CommandSpec.
KnifeCommand = SpecCommandProvider


class BundleHintProvider(Protocol):
    name: str

    def bundle_hints(self, case_dir: Path) -> Sequence[str]: ...


@dataclass
class PluginRegistry:
    presets: dict[str, FieldPreset] = field(default_factory=dict)
    physical_profiles: dict[str, PhysicalRuleProvider] = field(default_factory=dict)
    knife_commands: dict[str, KnifeCommand] = field(default_factory=dict)
    bundle_hints: dict[str, BundleHintProvider] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_preset(self, preset: FieldPreset) -> bool:
        return self._register(self.presets, preset.name, preset, "field preset")

    def add_physical_profile(self, provider: PhysicalRuleProvider) -> bool:
        return self._register(
            self.physical_profiles, provider.name, provider, "physical profile",
        )

    def add_knife_command(self, provider: KnifeCommand) -> bool:
        return self._register(
            self.knife_commands, provider.name, provider, "knife command",
        )

    def add_bundle_hint_provider(self, provider: BundleHintProvider) -> bool:
        return self._register(
            self.bundle_hints, provider.name, provider, "bundle hint provider",
        )

    def _register(self, target: dict[str, Any], name: str, value: Any, kind: str) -> bool:
        if name in target:
            self.errors.append(f"duplicate {kind} '{name}' ignored")
            return False
        target[name] = value
        return True


def builtin_registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.add_preset(
        FieldPreset(
            name="flow",
            fields=("p", "U", "rho", "T"),
            description="Generic OpenFOAM flow fields; missing fields are reported per case.",
        ),
    )
    return registry


def discover_plugins() -> PluginRegistry:
    registry = builtin_registry()
    try:
        eps = entry_points(group="ofti.plugins")
    except TypeError:  # pragma: no cover - compatibility with older importlib.metadata
        eps = entry_points().get("ofti.plugins", [])  # type: ignore[union-attr]
    for ep in eps:
        try:
            register = ep.load()
            register(registry)
        except Exception as exc:  # keep core commands usable if one plugin is broken
            registry.errors.append(f"{ep.name}: {exc}")
    return registry
