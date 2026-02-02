from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.tools.input_prompts import prompt_args_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _run_simple_tool
from ofti.tools.tool_dicts_utils import _ensure_tool_dict, _open_dict_preview


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
    args = prompt_args_line(stdscr, "> ")
    if args is None:
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
    args = prompt_args_line(stdscr, "> ")
    if args is None:
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
    menu = build_menu(
        stdscr,
        "Tool dictionaries",
        [*labels, "Back"],
        menu_key="menu:tool_dicts",
        item_hint="Open selected tool dict.",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    name, path, helper_cmd = items[choice]
    if not _ensure_tool_dict(stdscr, case_path, name, path, helper_cmd):
        return
    _open_dict_preview(stdscr, path)
