from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

from ofti.app.cli_adapters.command_builder import build_provider_parsers
from ofti.app.cli_help import _help_handler, emit_json
from ofti.plugins import PluginRegistry, discover_plugins
from ofti.tools import result_service


def _build_result_parser(
    groups: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    registry: PluginRegistry | None = None,
) -> None:
    selected_registry = registry or discover_plugins()
    result = groups.add_parser("result", help="Pack and unpack completed run results")
    result.set_defaults(func=_help_handler(result), plugin_registry=selected_registry)
    commands = result.add_subparsers(dest="result_command", required=False)

    pack = commands.add_parser("pack", help="Pack latest results, logs, and provenance")
    pack.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    pack.add_argument("--output", required=True, type=Path)
    pack.add_argument("--time", default="latest", help="Reconstructed time or latest")
    pack.add_argument(
        "--include-processors",
        action="store_true",
        help="Include selected processor fields and processor meshes",
    )
    pack.add_argument("--json", action="store_true")
    pack.set_defaults(func=_result_pack)

    unpack = commands.add_parser("unpack", help="Verify and extract a result pack")
    unpack.add_argument("archive", type=Path)
    unpack.add_argument("--to", required=True, type=Path)
    unpack.add_argument("--json", action="store_true")
    unpack.set_defaults(func=_result_unpack)

    build_provider_parsers(
        commands,
        selected_registry.result_commands,
        selected_registry.errors,
        surface="result",
    )


def _result_pack(args: argparse.Namespace) -> int:
    payload = result_service.pack_payload(
        args.case_dir,
        args.output,
        time_name=args.time,
        include_processors=args.include_processors,
    )
    return _print_result(payload, args)


def _result_unpack(args: argparse.Namespace) -> int:
    return _print_result(result_service.unpack_payload(args.archive, args.to), args)


def _print_result(payload: dict[str, object], args: argparse.Namespace) -> int:
    if args.json:
        emit_json(payload, args)
    else:
        print(f"archive={payload['archive']}")
        if payload.get("destination"):
            print(f"destination={payload['destination']}")
        manifest = cast("dict[str, Any]", payload["manifest"])
        print(f"files={len(manifest['files'])} time={manifest['selected_time']}")
    return 0
