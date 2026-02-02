from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from ofti.core.times import latest_time
from ofti.tools.runner import _run_simple_tool, _show_message
from ofti.tools.tool_dicts_utils import _ensure_tool_dict
from ofti.ui_curses.help import menu_hint
from ofti.ui_curses.inputs import prompt_input
from ofti.ui_curses.menus import Menu


def foam_calc_prompt(stdscr: Any, case_path: Path) -> None:  # noqa: C901, PLR0912
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
        menu = Menu(
            stdscr,
            "foamCalc",
            options,
            status_line=f"Latest time: {latest}",
            hint_provider=lambda idx: menu_hint("menu:foamcalc_menu", options[idx])
            if 0 <= idx < len(options)
            else "",
        )
        choice = menu.navigate()
        if choice in (-1, len(options) - 1):
            return
        if choice == 0:
            _run_simple_tool(stdscr, case_path, "foamCalc", ["foamCalc"])
            return
        if choice == 1:
            ops = ["mag", "grad", "div", "Back"]
            op_menu = Menu(
                stdscr,
                "foamCalc common ops",
                ops,
                hint_provider=lambda idx: (
                    "Select operator."
                    if 0 <= idx < len(ops) - 1
                    else menu_hint("menu:foamcalc_ops", "Back")
                ),
            )
            op_choice = op_menu.navigate()
            if op_choice == -1 or op_choice == len(ops) - 1:
                continue
            op = ops[op_choice]
            field = prompt_input(stdscr, f"{op} field (default U): ")
            if field is None:
                continue
            field = field.strip() or "U"
            cmd = ["foamCalc", op, field, "-latestTime"]
            if op == "div":
                flux = prompt_input(stdscr, "div flux field (default phi): ")
                if flux is None:
                    continue
                flux = flux.strip() or "phi"
                cmd = ["foamCalc", op, flux, field, "-latestTime"]
            _run_simple_tool(stdscr, case_path, f"foamCalc {op}", cmd)
            return
        if choice == 2:
            stdscr.clear()
            stdscr.addstr("foamCalc args (e.g. components U -latestTime):\n")
            stdscr.addstr(f"Tip: latest time detected = {latest}\n")
            args_line = prompt_input(stdscr, "> ")
            if args_line is None:
                return
            args_line = args_line.strip()
            if not args_line:
                _show_message(stdscr, "No arguments provided for foamCalc.")
                continue
            try:
                args = shlex.split(args_line)
            except ValueError as exc:
                _show_message(stdscr, f"Invalid arguments: {exc}")
                continue
            cmd = ["foamCalc", *args]
            _run_simple_tool(stdscr, case_path, "foamCalc", cmd)
            return
