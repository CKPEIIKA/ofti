#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ofti.app.app import run_tui
from ofti.app.cli_tools import main as cli_tools_main
from ofti.foam.openfoam import OpenFOAMError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofti",
        description="OpenFOAM TUI config editor",
        epilog="Non-interactive tools: ofti knife|plot|watch|run ...",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Entry point for the OpenFOAM TUI.

    Usage:
        ofti [--debug] [CASE_DIR]
    """
    args_in = list(argv) if argv is not None else sys.argv[1:]
    if args_in and args_in[0] in {"knife", "plot", "watch", "run"}:
        return cli_tools_main(args_in)

    parser = build_parser()
    args = parser.parse_args(args_in)

    try:
        run_tui(str(args.case_dir), debug=args.debug)
    except (OpenFOAMError, OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
        if args.debug:
            raise
        print(f"ofti error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
