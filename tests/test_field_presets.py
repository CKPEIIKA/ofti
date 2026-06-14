from __future__ import annotations

import pytest

from ofti.core.field_presets import available_field_preset_names, resolve_field_preset
from ofti.plugins import FieldPreset, PluginRegistry


def test_builtin_field_presets_are_generic() -> None:
    preset = resolve_field_preset("flow")

    assert preset.fields == ("p", "U", "rho", "T")
    assert preset.source == "core"
    assert available_field_preset_names() == ["flow"]


def test_unknown_field_preset_lists_available_names() -> None:
    with pytest.raises(ValueError, match="unknown field preset: plugin-preset; available: flow"):
        resolve_field_preset("plugin-preset")


def test_plugin_field_preset_resolves_through_registry(monkeypatch) -> None:
    registry = PluginRegistry(
        presets={
            "flow": FieldPreset("flow", ("p", "U")),
            "fake-flow": FieldPreset("fake-flow", ("rho", "T"), source="test"),
        },
    )
    monkeypatch.setattr("ofti.core.field_presets.discover_plugins", lambda: registry)

    assert available_field_preset_names() == ["fake-flow", "flow"]
    assert resolve_field_preset("fake-flow").fields == ("rho", "T")
