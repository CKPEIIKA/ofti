"""Neutral CLI output contract shared by core commands and plugins.

Every dictionary payload receives framework-owned schema and command metadata.
This module is pure so plugins can depend on it without importing the app layer.
"""

from __future__ import annotations

from typing import Any

JSON_SCHEMA_VERSION = 1


def command_name(args: object) -> str:
    """Derive the dotted command path from an argparse-style namespace."""
    parts = [
        getattr(args, "group", None),
        getattr(args, "bundle_command", None),
        getattr(args, "command", None),
        getattr(args, "manifest_command", None),
        getattr(args, "registry_command", None),
        getattr(args, "campaign_command", None),
        getattr(args, "result_command", None),
        getattr(args, "plugins_command", None),
    ]
    return " ".join(str(part) for part in parts if part)


def stamp_payload(payload: Any, command: str) -> Any:
    """Stamp a dictionary with authoritative schema and command metadata."""
    if isinstance(payload, dict):
        return {
            **payload,
            "schema_version": JSON_SCHEMA_VERSION,
            "command": command,
        }
    return payload
