#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ofti.app.app import run_tui
from ofti.foam.openfoam import OpenFOAMError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofti",
        description="OpenFOAM TUI config editor",
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
        "--no-foam",
        action="store_true",
        help="Run without OpenFOAM tools (view-only mode)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """
    Entry point for the OpenFOAM TUI.

    Usage:
        ofti [--debug] [CASE_DIR]
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        run_tui(str(args.case_dir), debug=args.debug, no_foam=args.no_foam)
    except (OpenFOAMError, OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
        if args.debug:
            raise
        print(f"ofti error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
