from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.entry_io import list_subkeys
from ofti.core.times import latest_time
from ofti.tools.input_prompts import prompt_args_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _run_simple_tool, _show_message
from ofti.ui_curses.tool_dicts_ui import _ensure_tool_dict


def post_process_prompt(stdscr: Any, case_path: Path) -> None:  # noqa: C901
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
            _run_simple_tool(stdscr, case_path, "postProcess", ["postProcess", "-latestTime"])
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
            _run_simple_tool(stdscr, case_path, "postProcess", cmd)
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
            _run_simple_tool(stdscr, case_path, "postProcess", cmd)
            return
