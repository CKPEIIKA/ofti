from __future__ import annotations

from importlib import import_module


def _help_module():
    return import_module("ofti.ui_curses.help")


def menu_hint(menu_key: str, label: str) -> str:
    return _help_module().menu_hint(menu_key, label)


def main_menu_help() -> list[str]:
    return _help_module().main_menu_help()


def tools_help() -> list[str]:
    return _help_module().tools_help()


def tools_physics_help() -> list[str]:
    return _help_module().tools_physics_help()
