from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from ofti.core.entry_io import list_subkeys
from ofti.core.times import latest_time
from ofti.tools.runner import _run_simple_tool, _show_message
from ofti.tools.tool_dicts_utils import _ensure_tool_dict
from ofti.ui_curses.help import menu_hint
from ofti.ui_curses.inputs import prompt_input
from ofti.ui_curses.menus import Menu


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
        menu = Menu(
            stdscr,
            "postProcess",
            options,
            status_line=f"Latest time: {latest}",
            hint_provider=lambda idx: menu_hint("menu:postprocess_menu", options[idx])
            if 0 <= idx < len(options)
            else "",
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
            func_menu = Menu(
                stdscr,
                "Select postProcess function",
                [*funcs, "Back"],
                hint_provider=lambda idx: (
                    "Select function."
                    if 0 <= idx < len(funcs)
                    else menu_hint("menu:postprocess_funcs", "Back")
                ),
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
            args_line = prompt_input(stdscr, "> ")
            if args_line is None:
                return
            args_line = args_line.strip()
            try:
                args = shlex.split(args_line) if args_line else ["-latestTime"]
            except ValueError as exc:
                _show_message(stdscr, f"Invalid arguments: {exc}")
                continue
            cmd = ["postProcess", *args]
            _run_simple_tool(stdscr, case_path, "postProcess", cmd)
            return
