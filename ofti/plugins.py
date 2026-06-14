from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol


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


class KnifeCommandProvider(Protocol):
    name: str

    def add_parser(self, subparsers: Any) -> None: ...

    def run(self, args: Any) -> int: ...


@dataclass
class PluginRegistry:
    presets: dict[str, FieldPreset] = field(default_factory=dict)
    physical_profiles: dict[str, PhysicalRuleProvider] = field(default_factory=dict)
    knife_commands: dict[str, KnifeCommandProvider] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_preset(self, preset: FieldPreset) -> None:
        self.presets[preset.name] = preset


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
