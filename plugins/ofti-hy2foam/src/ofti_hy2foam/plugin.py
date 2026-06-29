from __future__ import annotations

from ofti.plugins import PluginRegistry

from .bundle import Hy2FoamBundleHints
from .charge import Hy2FoamChargeCommand
from .compare import Hy2FoamComparePreflightCommand, Hy2FoamPatchCompareCommand
from .physical import Hy2FoamPhysicalProfile
from .preflight import Hy2FoamPreflightCommand
from .presets import AIR5, AIR11, TRANSPORT, TWO_TEMPERATURE, WALL


def register(registry: PluginRegistry) -> None:
    for preset in (AIR5, AIR11, TRANSPORT, TWO_TEMPERATURE, WALL):
        registry.add_preset(preset)
    registry.add_physical_profile(Hy2FoamPhysicalProfile())
    registry.add_knife_command(Hy2FoamChargeCommand())
    registry.add_knife_command(Hy2FoamPreflightCommand())
    registry.add_knife_command(Hy2FoamComparePreflightCommand())
    registry.add_knife_command(Hy2FoamPatchCompareCommand())
    registry.add_bundle_hint_provider(Hy2FoamBundleHints())
