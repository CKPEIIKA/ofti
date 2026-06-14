from __future__ import annotations

from ofti.plugins import FieldPreset, PluginRegistry, discover_plugins


def field_preset_registry() -> PluginRegistry:
    return discover_plugins()


def available_field_presets(registry: PluginRegistry | None = None) -> dict[str, FieldPreset]:
    return dict((registry or field_preset_registry()).presets)


def available_field_preset_names(registry: PluginRegistry | None = None) -> list[str]:
    return sorted(available_field_presets(registry))


def resolve_field_preset(name: str, registry: PluginRegistry | None = None) -> FieldPreset:
    presets = available_field_presets(registry)
    try:
        return presets[name]
    except KeyError as exc:
        available = ", ".join(sorted(presets)) or "none"
        raise ValueError(f"unknown field preset: {name}; available: {available}") from exc


def builtin_field_preset_map() -> dict[str, list[str]]:
    return {name: list(preset.fields) for name, preset in available_field_presets().items()}
