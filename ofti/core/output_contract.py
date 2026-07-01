"""Neutral CLI output contract shared by core commands and plugins.

Keeps machine-readable JSON a stable, versioned API: every dict payload is
stamped with ``schema_version`` and the originating ``command``. This module is
pure (no printing, no argparse/UI imports) so plugins can depend on it without
importing ``ofti.app``. Callers do their own ``json.dumps``/printing.
"""

from __future__ import annotations

from typing import Any

#: Bumped when the machine-readable JSON payload shape changes in a breaking way.
JSON_SCHEMA_VERSION = 1


def command_name(args: object) -> str:
    """Derive the dotted command path from an argparse-style namespace."""
    parts = [
        getattr(args, "group", None),
        getattr(args, "command", None),
        getattr(args, "manifest_command", None),
        getattr(args, "registry_command", None),
        getattr(args, "campaign_command", None),
    ]
    return " ".join(str(part) for part in parts if part)


def stamp_payload(payload: Any, command: str) -> Any:
    """Stamp a dict payload with schema_version/command (a payload's keys win)."""
    if isinstance(payload, dict) and "schema_version" not in payload:
        return {
            "schema_version": JSON_SCHEMA_VERSION,
            "command": command,
            **payload,
        }
    return payload
