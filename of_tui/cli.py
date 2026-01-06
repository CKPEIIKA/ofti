#!/usr/bin/env python3

import argparse
import os
import sys

from .app import run_tui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="of_tui",
        description="OpenFOAM TUI config editor",
    )
    parser.add_argument(
        "case_dir",
        nargs="?",
        default=os.getcwd(),
        help="Path to an OpenFOAM case directory (default: current directory)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging and more verbose error reporting",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """
    Entry point for the OpenFOAM TUI.

    Usage:
        of_tui [--debug] [CASE_DIR]
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        run_tui(args.case_dir, debug=args.debug)
    except Exception as exc:  # pragma: no cover - safety net
        if args.debug:
            raise
        print(f"of_tui error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
