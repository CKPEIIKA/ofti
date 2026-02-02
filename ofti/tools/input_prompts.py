from __future__ import annotations

import shlex
from typing import Any

from ofti.tools.runner import _show_message
from ofti.ui_curses.inputs import prompt_input


def prompt_line(stdscr: Any, prompt: str) -> str | None:
    value = prompt_input(stdscr, prompt)
    if value is None:
        return None
    return value.strip()


def prompt_args_line(stdscr: Any, prompt: str) -> list[str] | None:
    value = prompt_line(stdscr, prompt)
    if value is None:
        return None
    if not value:
        return []
    try:
        return shlex.split(value)
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return None


def prompt_command_line(stdscr: Any, prompt: str) -> list[str] | None:
    args = prompt_args_line(stdscr, prompt)
    if args is None:
        return None
    if not args:
        _show_message(stdscr, "No command provided.")
        return None
    return args
