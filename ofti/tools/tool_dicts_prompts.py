from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from ofti.tools.runner import _run_simple_tool, _show_message
from ofti.tools.tool_dicts_utils import _ensure_tool_dict, _open_dict_preview
from ofti.ui_curses.help import menu_hint
from ofti.ui_curses.inputs import prompt_input
from ofti.ui_curses.menus import Menu


def topo_set_prompt(stdscr: Any, case_path: Path) -> None:
    """Prompt for topoSet arguments."""
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "topoSet",
        case_path / "system" / "topoSetDict",
        ["topoSetDict"],
    ):
        return
    stdscr.clear()
    stdscr.addstr("topoSet args (press Enter to run with defaults):\n")
    args_line = prompt_input(stdscr, "> ")
    if args_line is None:
        return
    args_line = args_line.strip()

    try:
        args = shlex.split(args_line) if args_line else []
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["topoSet", *args]
    _run_simple_tool(stdscr, case_path, "topoSet", cmd)


def set_fields_prompt(stdscr: Any, case_path: Path) -> None:
    """Prompt for setFields arguments."""
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "setFields",
        case_path / "system" / "setFieldsDict",
        None,
    ):
        return
    stdscr.clear()
    stdscr.addstr("setFields args (press Enter to run with defaults):\n")
    args_line = prompt_input(stdscr, "> ")
    if args_line is None:
        return
    args_line = args_line.strip()

    try:
        args = shlex.split(args_line) if args_line else []
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["setFields", *args]
    _run_simple_tool(stdscr, case_path, "setFields", cmd)


def tool_dicts_screen(stdscr: Any, case_path: Path) -> None:
    items = [
        ("postProcess", case_path / "system" / "postProcessDict", ["postProcess", "-list"]),
        ("foamCalc", case_path / "system" / "foamCalcDict", ["foamCalc", "-help"]),
        ("topoSet", case_path / "system" / "topoSetDict", ["topoSetDict"]),
        ("setFields", case_path / "system" / "setFieldsDict", None),
    ]
    labels = [f"{name}: {path.relative_to(case_path)}" for name, path, _ in items]
    menu = Menu(
        stdscr,
        "Tool dictionaries",
        [*labels, "Back"],
        hint_provider=lambda idx: (
            "Open selected tool dict."
            if 0 <= idx < len(labels)
            else menu_hint("menu:tool_dicts", "Back")
        ),
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    name, path, helper_cmd = items[choice]
    if not _ensure_tool_dict(stdscr, case_path, name, path, helper_cmd):
        return
    _open_dict_preview(stdscr, path)
