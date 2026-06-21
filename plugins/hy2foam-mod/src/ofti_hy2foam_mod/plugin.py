from __future__ import annotations

from ofti.plugins import PluginRegistry

from .preflight import Hy2FoamModPreflightCommand


def register(registry: PluginRegistry) -> None:
    registry.add_knife_command(Hy2FoamModPreflightCommand())
