from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.tool_screens.menu_helpers import build_menu
from ofti.app.tool_screens.runner import _show_message, run_tool_command
from ofti.core.entry_io import list_subkeys
from ofti.core.times import latest_time
from ofti.ui_curses.prompts import prompt_args_line
from ofti.ui_curses.tool_dicts_ui import _ensure_tool_dict


def post_process_prompt(stdscr: Any, case_path: Path) -> None:
    """Prompt for postProcess arguments, suggesting use of latestTime."""
    latest = latest_time(case_path)
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "postProcess",
        case_path / "system" / "postProcessDict",
        ["postProcess", "-list"],
    ):
        return
    while True:
        options = [
            "Run with defaults (-latestTime)",
            "Select function from postProcessDict",
            "Enter args manually",
            "Back",
        ]
        menu = build_menu(
            stdscr,
            "postProcess",
            options,
            menu_key="menu:postprocess_menu",
            status_line=f"Latest time: {latest}",
        )
        choice = menu.navigate()
        if choice in (-1, len(options) - 1):
            return
        if choice == 0:
            run_tool_command(
                stdscr,
                case_path,
                "postProcess",
                ["postProcess", "-latestTime"],
                status="Running postProcess...",
            )
            return
        if choice == 1:
            dict_path = case_path / "system" / "postProcessDict"
            funcs = list_subkeys(dict_path, "functions")
            if not funcs:
                _show_message(stdscr, "No functions found in postProcessDict.")
                continue
            func_menu = build_menu(
                stdscr,
                "Select postProcess function",
                [*funcs, "Back"],
                menu_key="menu:postprocess_funcs",
                item_hint="Select function.",
            )
            func_choice = func_menu.navigate()
            if func_choice in (-1, len(funcs)):
                continue
            func = funcs[func_choice]
            cmd = ["postProcess", "-latestTime", "-funcs", f"({func})"]
            run_tool_command(
                stdscr,
                case_path,
                "postProcess",
                cmd,
                status="Running postProcess...",
            )
            return
        if choice == 2:
            stdscr.clear()
            stdscr.addstr("postProcess args (e.g. -latestTime -funcs '(mag(U))'):\n")
            stdscr.addstr(f"Tip: latest time detected = {latest}\n")
            args = prompt_args_line(stdscr, "> ")
            if args is None:
                return
            if not args:
                args = ["-latestTime"]
            cmd = ["postProcess", *args]
            run_tool_command(
                stdscr,
                case_path,
                "postProcess",
                cmd,
                status="Running postProcess...",
            )
            return
