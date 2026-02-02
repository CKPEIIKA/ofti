from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.foam.subprocess_utils import run_trusted
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _run_simple_tool, _show_message, _write_tool_log


def _decomposed_processors(case_path: Path) -> list[Path]:
    return sorted(p for p in case_path.iterdir() if p.is_dir() and p.name.startswith("processor"))


def reconstruct_manager_screen(stdscr: Any, case_path: Path) -> None:
    processors = _decomposed_processors(case_path)
    if not processors:
        _show_message(stdscr, "Case is not decomposed (no processor* directories).")
        return
    options = ["reconstructPar", "reconstructPar -latestTime", "Back"]
    menu = build_menu(
        stdscr,
        "Reconstruct manager",
        options,
        menu_key="menu:reconstruct_manager",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(options) - 1:
        return
    if choice == 0:
        _run_simple_tool(stdscr, case_path, "reconstructPar", ["reconstructPar"])
    elif choice == 1:
        _run_simple_tool(
            stdscr, case_path, "reconstructPar -latestTime", ["reconstructPar", "-latestTime"],
        )


def reconstruct_latest_once(case_path: Path) -> tuple[bool, str]:
    processors = _decomposed_processors(case_path)
    if not processors:
        return False, "No processor directories found (skip reconstruct)."
    try:
        result = run_trusted(
            ["reconstructPar", "-latestTime"],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, f"reconstructPar failed: {exc}"
    _write_tool_log(case_path, "reconstructPar", result.stdout, result.stderr)
    if result.returncode != 0:
        return False, f"reconstructPar exit code {result.returncode}"
    return True, "reconstructPar -latestTime completed."
