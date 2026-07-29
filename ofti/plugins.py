from __future__ import annotations

from collections.abc import Mapping, Sequence
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
    """A command provider that declares a framework-neutral CommandSpec.

    The CLI adapter builds argparse from the spec, so the plugin never touches
    argparse internals. ``command_spec().handler`` is the run callable.
    """

    name: str

    def command_spec(self) -> CommandSpec: ...

    def run(self, args: Any) -> int: ...


#: A knife command declares a framework-neutral CommandSpec.
KnifeCommand = SpecCommandProvider
RunCommand = SpecCommandProvider
WatchCommand = SpecCommandProvider
ResultCommand = SpecCommandProvider


class ProgressMetricProvider(Protocol):
    """Add domain-specific, read-only evidence to a case progress payload."""

    name: str

    def progress_metrics(
        self,
        case_dir: Path,
        *,
        log_path: Path | None = None,
    ) -> Mapping[str, object]: ...


class BundleHintProvider(Protocol):
    name: str

    def bundle_hints(self, case_dir: Path) -> Sequence[str]: ...


@dataclass(frozen=True)
class PluginRecord:
    """One discovered entry point and the surfaces it registered."""

    name: str
    entry_point: str
    distribution: str | None
    version: str | None
    status: str
    registrations: dict[str, tuple[str, ...]] = field(default_factory=dict)
    errors: tuple[str, ...] = ()


@dataclass
class PluginRegistry:
    presets: dict[str, FieldPreset] = field(default_factory=dict)
    physical_profiles: dict[str, PhysicalRuleProvider] = field(default_factory=dict)
    knife_commands: dict[str, KnifeCommand] = field(default_factory=dict)
    run_commands: dict[str, RunCommand] = field(default_factory=dict)
    watch_commands: dict[str, WatchCommand] = field(default_factory=dict)
    result_commands: dict[str, ResultCommand] = field(default_factory=dict)
    progress_metrics: dict[str, ProgressMetricProvider] = field(default_factory=dict)
    bundle_hints: dict[str, BundleHintProvider] = field(default_factory=dict)
    plugins: list[PluginRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add_preset(self, preset: FieldPreset) -> bool:
        return self._register(self.presets, preset.name, preset, "field preset")

    def add_physical_profile(self, provider: PhysicalRuleProvider) -> bool:
        return self._register(
            self.physical_profiles,
            provider.name,
            provider,
            "physical profile",
        )

    def add_knife_command(self, provider: KnifeCommand) -> bool:
        return self._register(
            self.knife_commands,
            provider.name,
            provider,
            "knife command",
        )

    def add_run_command(self, provider: RunCommand) -> bool:
        return self._register(self.run_commands, provider.name, provider, "run command")

    def add_watch_command(self, provider: WatchCommand) -> bool:
        return self._register(self.watch_commands, provider.name, provider, "watch command")

    def add_result_command(self, provider: ResultCommand) -> bool:
        return self._register(self.result_commands, provider.name, provider, "result command")

    def add_progress_metric(self, provider: ProgressMetricProvider) -> bool:
        return self._register(
            self.progress_metrics,
            provider.name,
            provider,
            "progress metric",
        )

    def add_bundle_hint_provider(self, provider: BundleHintProvider) -> bool:
        return self._register(
            self.bundle_hints,
            provider.name,
            provider,
            "bundle hint provider",
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
    for ep in entry_points(group="ofti.plugins"):
        before = _registration_snapshot(registry)
        error_start = len(registry.errors)
        status = "loaded"
        try:
            _load_plugin_entry_point(ep, registry)
        except Exception as exc:  # keep core commands usable if one plugin is broken
            status = "failed"
            registry.errors.append(f"{ep.name}: {exc}")
        registry.plugins.append(
            PluginRecord(
                name=ep.name,
                entry_point=ep.value,
                distribution=_entry_point_distribution(ep),
                version=_entry_point_version(ep),
                status=status,
                registrations=_registrations_since(registry, before),
                errors=tuple(registry.errors[error_start:]),
            ),
        )
    return registry


def _load_plugin_entry_point(entry_point: Any, registry: PluginRegistry) -> None:
    register = entry_point.load()
    if not callable(register):
        raise TypeError("entry point must resolve to a callable register(registry)")
    register(registry)


def _registration_snapshot(registry: PluginRegistry) -> dict[str, set[str]]:
    return {name: set(values) for name, values in _registration_maps(registry).items()}


def _registrations_since(
    registry: PluginRegistry,
    before: dict[str, set[str]],
) -> dict[str, tuple[str, ...]]:
    return {
        name: tuple(sorted(set(values).difference(before.get(name, set()))))
        for name, values in _registration_maps(registry).items()
        if set(values).difference(before.get(name, set()))
    }


def _registration_maps(registry: PluginRegistry) -> dict[str, Mapping[str, object]]:
    return {
        "presets": registry.presets,
        "physical_profiles": registry.physical_profiles,
        "knife_commands": registry.knife_commands,
        "run_commands": registry.run_commands,
        "watch_commands": registry.watch_commands,
        "result_commands": registry.result_commands,
        "progress_metrics": registry.progress_metrics,
        "bundle_hints": registry.bundle_hints,
    }


def _entry_point_distribution(entry_point: Any) -> str | None:
    distribution = getattr(entry_point, "dist", None)
    metadata = getattr(distribution, "metadata", None)
    if metadata is not None:
        name = metadata.get("Name")
        if name:
            return str(name)
    name = getattr(distribution, "name", None)
    return str(name) if name else None


def _entry_point_version(entry_point: Any) -> str | None:
    distribution = getattr(entry_point, "dist", None)
    version = getattr(distribution, "version", None)
    return str(version) if version else None
