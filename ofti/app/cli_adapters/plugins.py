from __future__ import annotations

import argparse
from typing import Any, cast

from ofti.app.cli_help import _help_handler, emit_json
from ofti.plugins import PluginRegistry, discover_plugins
from ofti.tools import plugin_service


def _build_plugins_parser(
    groups: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    registry: PluginRegistry | None = None,
) -> None:
    selected = registry or discover_plugins()
    plugins = groups.add_parser(
        "plugins",
        help="Inspect installed OFTI plugins",
        description="Show plugin versions, entry-point sources, registrations, and load failures.",
    )
    plugins.set_defaults(func=_help_handler(plugins), plugin_registry=selected)
    commands = plugins.add_subparsers(dest="plugins_command", required=False)

    list_cmd = commands.add_parser("list", help="List discovered plugins and registered surfaces")
    list_cmd.add_argument("--json", action="store_true", help="Print result as JSON")
    list_cmd.set_defaults(func=_plugins_list)

    doctor = commands.add_parser("doctor", help="Fail on plugin load or registration problems")
    doctor.add_argument("--json", action="store_true", help="Print result as JSON")
    doctor.set_defaults(func=_plugins_doctor)


def _plugins_list(args: argparse.Namespace) -> int:
    payload = plugin_service.list_payload(args.plugin_registry)
    _render_payload(payload, args)
    return 0


def _plugins_doctor(args: argparse.Namespace) -> int:
    payload = plugin_service.doctor_payload(args.plugin_registry)
    _render_payload(payload, args)
    return 0 if payload["ok"] else 1


def _render_payload(payload: dict[str, Any], args: argparse.Namespace) -> None:
    if args.json:
        emit_json(payload, args)
        return
    print(
        f"plugins={payload['plugin_count']} loaded={payload['loaded']} failed={payload['failed']} ok={payload['ok']}",
    )
    for row in cast("list[dict[str, Any]]", payload["plugins"]):
        version = row.get("version") or "unknown"
        distribution = row.get("distribution") or "unknown"
        print(
            f"- {row['name']} {version} [{row['status']}] distribution={distribution} entry_point={row['entry_point']}",
        )
        registrations = cast("dict[str, list[str]]", row["registrations"])
        for surface, names in sorted(registrations.items()):
            print(f"  {surface}: {', '.join(names)}")
        for error in row["errors"]:
            print(f"  error: {error}")
    for warning in payload.get("warnings", []):
        print(f"warning: {warning}")
    for error in payload["errors"]:
        print(f"error: {error}")
