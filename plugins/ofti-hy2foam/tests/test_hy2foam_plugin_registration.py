# ruff: noqa: INP001
from __future__ import annotations

import sys
from pathlib import Path

from ofti.plugins import PluginRegistry

PLUGIN_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SRC))

from ofti_hy2foam.plugin import register  # noqa: E402


def test_hy2foam_plugin_registers_presets_profile_and_charge_command() -> None:
    registry = PluginRegistry()

    register(registry)

    assert registry.presets["air5"].source == "ofti-hy2foam"
    assert registry.presets["air11"].fields[-2:] == ("p", "rho")
    assert registry.presets["hy2foam-transport"].fields[-1] == "qDiff"
    assert registry.presets["hy2foam-2T"].fields == ("Tt", "Tv", "Tov", "e", "ev")
    assert registry.presets["hy2foam-wall"].fields[0] == "wallHeatFlux"
    assert "hy2foam" in registry.physical_profiles
    assert "charge" in registry.knife_commands
    assert "hy2foam-preflight" in registry.knife_commands
    assert "hy2foam-compare-check" in registry.knife_commands
    assert "hy2foam-patch-compare" in registry.knife_commands
