from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.tool_screens.menu_helpers import build_menu
from ofti.app.tool_screens.runner import _show_message, _write_tool_log, run_tool_command
from ofti.foam.subprocess_utils import run_trusted
from ofti.foamlib import runner as foamlib_runner
from ofti.foamlib.adapter import FoamlibUnavailableError


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
        ok, message = reconstruct_all_once(case_path)
        if ok:
            _show_message(stdscr, message)
            return
        if message == "foamlib unavailable":
            run_tool_command(
                stdscr,
                case_path,
                "reconstructPar",
                ["reconstructPar"],
                status="Running reconstructPar...",
            )
            return
        _show_message(stdscr, message)
    elif choice == 1:
        run_tool_command(
            stdscr,
            case_path,
            "reconstructPar -latestTime",
            ["reconstructPar", "-latestTime"],
            status="Running reconstructPar -latestTime...",
        )


def reconstruct_all_once(case_path: Path) -> tuple[bool, str]:
    processors = _decomposed_processors(case_path)
    if not processors:
        return False, "No processor directories found (skip reconstruct)."
    try:
        foamlib_runner.reconstruct_case(case_path, check=True, log="log.reconstructPar")
    except FoamlibUnavailableError:
        return False, "foamlib unavailable"
    except Exception as exc:
        return False, f"reconstructPar failed: {exc}"
    return True, "reconstructPar completed."


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
