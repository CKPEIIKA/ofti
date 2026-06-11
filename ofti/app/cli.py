#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ofti.app.app import run_tui
from ofti.app.cli_tools import main as cli_tools_main
from ofti.foam.openfoam import OpenFOAMError

_CLI_TOOLS_GROUPS = {"knife", "plot", "watch", "run", "version"}
_CLI_VERSION_FLAGS = {"-V", "--version"}
_DECK_GROUP = "tui"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofti",
        description="OpenFOAM TUI config editor",
        epilog=(
            "Non-interactive tools: ofti knife|plot|watch|run ... "
            "Mission control deck: ofti tui [CASE_DIR]"
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
        "-V",
        "--version",
        action="store_true",
        help="Show version and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the OpenFOAM TUI.

    Usage:
        ofti [--debug] [CASE_DIR]
    """
    args_in = list(argv) if argv is not None else sys.argv[1:]
    use_cli_tools = args_in and (
        args_in[0] in _CLI_TOOLS_GROUPS or any(flag in args_in for flag in _CLI_VERSION_FLAGS)
    )
    if use_cli_tools:
        return cli_tools_main(args_in)
    if args_in and args_in[0] == _DECK_GROUP:
        return _run_deck(args_in[1:])

    parser = build_parser()
    args = parser.parse_args(args_in)
    if bool(getattr(args, "version", False)):
        return cli_tools_main(["--version"])

    try:
        run_tui(str(args.case_dir), debug=args.debug)
    except (OpenFOAMError, OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
        if args.debug:
            raise
        print(f"ofti error: {exc}", file=sys.stderr)
        return 1
    return 0


def _build_deck_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofti tui",
        description=(
            "Mission control deck (optional Textual UI). "
            "Falls back to the classic curses TUI when the 'tui' extra is missing."
        ),
    )
    parser.add_argument(
        "case_dir",
        nargs="?",
        default=Path.cwd(),
        help="Path to an OpenFOAM case directory (default: current directory)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Deck auto-refresh interval in seconds; 0 disables (default: 3)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable more verbose error reporting",
    )
    return parser


def _run_deck(args_in: list[str]) -> int:
    from ofti import ui_textual

    args = _build_deck_parser().parse_args(args_in)
    case_path = Path(args.case_dir)
    if not ui_textual.textual_available():
        print(f"ofti: {ui_textual.TUI_EXTRA_HINT}", file=sys.stderr)
        print("ofti: opening the classic curses TUI instead.", file=sys.stderr)
        try:
            run_tui(str(case_path), debug=args.debug)
        except (OpenFOAMError, OSError, RuntimeError, ValueError) as exc:
            if args.debug:
                raise
            print(f"ofti error: {exc}", file=sys.stderr)
            return 1
        return 0
    from ofti.ui_textual.app import run_mission_control

    try:
        return run_mission_control(case_path, interval=float(args.interval))
    except (OpenFOAMError, OSError, RuntimeError, ValueError) as exc:
        if args.debug:
            raise
        print(f"ofti error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
