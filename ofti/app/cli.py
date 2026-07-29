#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ofti.app.app import run_tui
from ofti.app.cli_tools import main as cli_tools_main
from ofti.foam.openfoam import OpenFOAMError

_CLI_TOOLS_GROUPS = {
    "knife",
    "plot",
    "watch",
    "run",
    "bundle",
    "result",
    "plugins",
    "version",
}
_CLI_VERSION_FLAGS = {"-V", "--version"}
_PLAIN_FLAGS = {"--plain", "--no-tty"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofti",
        description="OpenFOAM CLI utilities with an interactive curses TUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ofti CASE\n"
            "  ofti knife preflight CASE --json\n"
            "  ofti run solver CASE --dry-run\n"
            "  ofti bundle case CASE --output case.ofti.tar.gz\n"
            "  ofti bundle extract case.ofti.tar.gz --to CASE_COPY --run --background\n"
            "  ofti bundle set CASE_A CASE_B --output study.ofti-set.tar.gz\n\n"
            "Non-interactive tools: ofti knife|plot|watch|run|bundle|result|plugins|version ..."
        ),
    )
    parser.add_argument(
        "case_dir",
        nargs="?",
        default=Path.cwd(),
        help="Path to an OpenFOAM case directory (default: current directory)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging and more verbose error reporting",
    )
    parser.add_argument(
        "--plain",
        "--no-tty",
        action="store_true",
        help="Never start curses; require an explicit non-interactive command",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="Show version and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for OFTI CLI groups or the interactive TUI.

    Usage:
        ofti [--debug] [CASE_DIR]
    """
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    args_in, plain = _strip_plain_flags(raw_args)
    use_cli_tools = args_in and (args_in[0] in _CLI_TOOLS_GROUPS or any(flag in args_in for flag in _CLI_VERSION_FLAGS))
    if use_cli_tools:
        return cli_tools_main(args_in)

    parser = build_parser()
    args = parser.parse_args(args_in)
    if bool(getattr(args, "version", False)):
        return cli_tools_main(["--version"])
    if plain:
        print(
            "ofti: --plain/--no-tty requires a non-interactive command (for example: ofti knife status CASE --json)",
            file=sys.stderr,
        )
        return 2
    if not _has_interactive_terminal():
        print(
            "ofti: interactive TUI requires a terminal; use --plain with "
            "a command such as `ofti knife status CASE --json`",
            file=sys.stderr,
        )
        return 2

    try:
        run_tui(str(args.case_dir), debug=args.debug)
    except (OpenFOAMError, OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
        if args.debug:
            raise
        print(f"ofti error: {exc}", file=sys.stderr)
        return 1
    return 0


def _strip_plain_flags(args: list[str]) -> tuple[list[str], bool]:
    plain = any(arg in _PLAIN_FLAGS for arg in args)
    return [arg for arg in args if arg not in _PLAIN_FLAGS], plain


def _has_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


if __name__ == "__main__":
    raise SystemExit(main())
