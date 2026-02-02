from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ofti.ui_curses.viewer import Viewer

from .manager import help_registry


def context_help(name: str) -> list[str]:
    return help_registry.context(name)


def main_menu_help() -> list[str]:
    return context_help("main")


def preprocessing_help() -> list[str]:
    return context_help("preprocessing")


def physics_help() -> list[str]:
    return context_help("physics")


def simulation_help() -> list[str]:
    return context_help("simulation")


def postprocessing_help() -> list[str]:
    return context_help("postprocessing")


def config_help() -> list[str]:
    return context_help("config")


def tools_help() -> list[str]:
    return context_help("tools")


def tools_physics_help() -> list[str]:
    return context_help("tools_physics")


def diagnostics_help() -> list[str]:
    return context_help("diagnostics")


def clean_case_help() -> list[str]:
    return context_help("clean")


def register_tool(name: str, lines: Iterable[str]) -> None:
    help_registry.register_tool(name, lines)


def tool_help(name: str) -> list[str]:
    return help_registry.tool(name)


def menu_hint(menu_key: str, label: str) -> str:
    return help_registry.menu_hint(menu_key, label)


def show_tool_help(stdscr: Any, title: str, tool_name: str) -> None:
    lines = tool_help(tool_name)
    if not lines:
        return
    content = "\n".join([title, "", *lines])
    Viewer(stdscr, content).display()
