from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from textwrap import dedent

from ofti.app.cli_adapters.knife import _build_knife_parser
from ofti.app.cli_adapters.plot import _build_plot_parser
from ofti.app.cli_adapters.run import _build_run_parser
from ofti.app.cli_adapters.watch import _build_watch_parser
from ofti.app.cli_help import (
    _fill_missing_help,
    _help_handler,
    _output_mode_conflict,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofti",
        description=(
            "Non-interactive OFTI utilities.\n"
            "Use --json for machine output and --table for aligned diagnostics."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent(
            """\
            Examples:
              ofti knife preflight CASE
              ofti watch log CASE --lines 80
              ofti run tool --list --case CASE
              ofti run tool blockMesh --case CASE --background
              ofti run solver CASE --parallel 8 --dry-run
              ofti run parametric CASE --entry application --values simpleFoam,pisoFoam
            """,
        ),
    )
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="Show version and exit",
    )
    parser.set_defaults(func=_help_handler(parser))
    groups = parser.add_subparsers(dest="group", required=False)

    _build_knife_parser(groups)
    _build_plot_parser(groups)
    _build_watch_parser(groups)
    _build_run_parser(groups)
    version_cmd = groups.add_parser("version", help="Show version and exit")
    version_cmd.set_defaults(func=_version_command)
    _fill_missing_help(parser)
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if bool(getattr(args, "version", False)):
        print(f"ofti {ofti_version()}")
        return 0
    if _output_mode_conflict(args):
        print("ofti: --json and --table cannot be used together", file=sys.stderr)
        return 2
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 2

def ofti_version() -> str:
    try:
        return package_version("ofti")
    except PackageNotFoundError:
        return "dev"

def _version_command(_args: argparse.Namespace) -> int:
    print(f"ofti {ofti_version()}")
    return 0

