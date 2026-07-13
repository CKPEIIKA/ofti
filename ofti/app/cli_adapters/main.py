from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from textwrap import dedent

from ofti.app.cli_adapters.bundle import _build_bundle_parser
from ofti.app.cli_adapters.knife_parser import _build_knife_parser
from ofti.app.cli_adapters.plot import _build_plot_parser
from ofti.app.cli_adapters.result import _build_result_parser
from ofti.app.cli_adapters.run import _build_run_parser
from ofti.app.cli_adapters.watch import _build_watch_parser
from ofti.app.cli_help import (
    _fill_missing_help,
    _help_handler,
    _output_mode_conflict,
    strip_json_version_args,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofti",
        description=(
            "Non-interactive OFTI utilities.\nUse --json for machine output and --table for aligned diagnostics."
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
              ofti bundle case CASE --output case.ofti.tar.gz
              ofti bundle set CASE_A CASE_B --output study.ofti-set.tar.gz
              ofti bundle extract study.ofti-set.tar.gz --to STUDY
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
    parser.add_argument(
        "--json-version",
        choices=("1", "2"),
        default=None,
        help="Machine JSON schema version for --json output (1 default, 2 stable envelope)",
    )
    parser.set_defaults(func=_help_handler(parser))
    groups = parser.add_subparsers(dest="group", required=False)

    _build_knife_parser(groups)
    _build_plot_parser(groups)
    _build_watch_parser(groups)
    _build_run_parser(groups)
    _build_bundle_parser(groups)
    _build_result_parser(groups)
    version_cmd = groups.add_parser("version", help="Show version and exit")
    version_cmd.set_defaults(func=_version_command)
    _fill_missing_help(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else list(argv)
    try:
        parsed_argv, json_version = strip_json_version_args(raw_argv)
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 2
    args = build_parser().parse_args(parsed_argv)
    if json_version is not None:
        args.json_version = json_version
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
