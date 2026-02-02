from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ofti.tools.runner import _show_message


def copy_zero_to_orig(stdscr: Any, case_path: Path) -> None:
    zero_dir = case_path / "0"
    dest = case_path / "0.orig"
    if not zero_dir.is_dir():
        _show_message(stdscr, "Source 0 directory is missing.")
        return
    try:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(zero_dir, dest, symlinks=True)
    except OSError as exc:
        _show_message(stdscr, f"Failed to copy 0 -> 0.orig: {exc}")
        return
    _show_message(stdscr, "Copied 0 to 0.orig successfully.")
