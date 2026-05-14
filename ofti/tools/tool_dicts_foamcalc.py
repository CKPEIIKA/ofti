from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.foam.times import latest_time
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _show_message, run_tool_command
from ofti.ui_curses.prompts import prompt_args_line, prompt_line
from ofti.ui_curses.tool_dicts_ui import _ensure_tool_dict


def foam_calc_prompt(stdscr: Any, case_path: Path) -> None:
    """Prompt for foamCalc arguments with helpers."""
    latest = latest_time(case_path)
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "foamCalc",
        case_path / "system" / "foamCalcDict",
        ["foamCalc", "-help"],
    ):
        return
    while True:
        options = [
            "Run with foamCalcDict",
            "Common ops (mag/grad/div)",
            "Enter args manually",
            "Back",
        ]
        menu = build_menu(
            stdscr,
            "foamCalc",
            options,
            menu_key="menu:foamcalc_menu",
            status_line=f"Latest time: {latest}",
        )
        choice = menu.navigate()
        if choice in (-1, len(options) - 1):
            return
        if choice == 0:
            run_tool_command(
                stdscr,
                case_path,
                "foamCalc",
                ["foamCalc"],
                status="Running foamCalc...",
            )
            return
        if choice == 1:
            ops = ["mag", "grad", "div", "Back"]
            op_menu = build_menu(
                stdscr,
                "foamCalc common ops",
                ops,
                menu_key="menu:foamcalc_ops",
                item_hint="Select operator.",
            )
            op_choice = op_menu.navigate()
            if op_choice == -1 or op_choice == len(ops) - 1:
                continue
            op = ops[op_choice]
            field = prompt_line(stdscr, f"{op} field (default U): ")
            if field is None:
                continue
            field = field or "U"
            cmd = ["foamCalc", op, field, "-latestTime"]
            if op == "div":
                flux = prompt_line(stdscr, "div flux field (default phi): ")
                if flux is None:
                    continue
                flux = flux or "phi"
                cmd = ["foamCalc", op, flux, field, "-latestTime"]
            run_tool_command(
                stdscr,
                case_path,
                f"foamCalc {op}",
                cmd,
                status=f"Running foamCalc {op}...",
            )
            return
        if choice == 2:
            stdscr.clear()
            stdscr.addstr("foamCalc args (e.g. components U -latestTime):\n")
            stdscr.addstr(f"Tip: latest time detected = {latest}\n")
            args = prompt_args_line(stdscr, "> ")
            if args is None:
                return
            if not args:
                _show_message(stdscr, "No arguments provided for foamCalc.")
                continue
            cmd = ["foamCalc", *args]
            run_tool_command(
                stdscr,
                case_path,
                "foamCalc",
                cmd,
                status="Running foamCalc...",
            )
            return
