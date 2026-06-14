from __future__ import annotations

from ofti.plugins import PluginRegistry

from .charge import Hy2FoamChargeCommand
from .compare import Hy2FoamComparePreflightCommand, Hy2FoamPatchCompareCommand
from .physical import Hy2FoamPhysicalProfile
from .preflight import Hy2FoamPreflightCommand
from .presets import AIR5, AIR11, TRANSPORT, TWO_TEMPERATURE, WALL


def register(registry: PluginRegistry) -> None:
    for preset in (AIR5, AIR11, TRANSPORT, TWO_TEMPERATURE, WALL):
        registry.add_preset(preset)
    registry.physical_profiles["hy2foam"] = Hy2FoamPhysicalProfile()
    registry.knife_commands["charge"] = Hy2FoamChargeCommand()
    registry.knife_commands["hy2foam-preflight"] = Hy2FoamPreflightCommand()
    registry.knife_commands["hy2foam-compare-check"] = Hy2FoamComparePreflightCommand()
    registry.knife_commands["hy2foam-patch-compare"] = Hy2FoamPatchCompareCommand()
