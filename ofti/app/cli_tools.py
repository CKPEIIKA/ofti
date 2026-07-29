"""Compatibility entry point for the non-interactive CLI.

Command parsers and handlers live in :mod:`ofti.app.cli_adapters`; this module
keeps the original import path for the three supported dispatcher functions.
Private adapter handlers are intentionally not re-exported.
"""

from __future__ import annotations

from ofti.app.cli_adapters.main import build_parser, main, ofti_version

__all__ = ["build_parser", "main", "ofti_version"]


if __name__ == "__main__":
    raise SystemExit(main())
