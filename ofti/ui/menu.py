from __future__ import annotations

from importlib import import_module
from typing import Any


def _menus_module() -> Any:
    return import_module("ofti.ui_curses.menus")


class Menu:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        return _menus_module().Menu(*args, **kwargs)

    def navigate(self) -> int:
        raise NotImplementedError

    def display(self) -> None:
        raise NotImplementedError


class RootMenu:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        return _menus_module().RootMenu(*args, **kwargs)

    def navigate(self) -> int:
        raise NotImplementedError


class Submenu:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        return _menus_module().Submenu(*args, **kwargs)

    def navigate(self) -> int:
        raise NotImplementedError
