from __future__ import annotations

import curses
import types

import pytest

from ofti.foam.config import Config
from ofti.foam.exceptions import QuitAppError
from ofti.ui_curses import menus


class _Screen:
    def __init__(self, keys: list[int] | None = None, height: int = 20, width: int = 60) -> None:
        self._keys = list(keys or [])
        self.height = height
        self.width = width
        self.lines: list[str] = []

    def clear(self) -> None:
        self.lines.clear()

    def erase(self) -> None:
        self.lines.clear()

    def getmaxyx(self) -> tuple[int, int]:
        return (self.height, self.width)

    def addstr(self, *args: object) -> None:
        self.lines.append(str(args[-1]))

    def attron(self, *_args: object, **_kwargs: object) -> None:
        return None

    def attroff(self, *_args: object, **_kwargs: object) -> None:
        return None

    def refresh(self) -> None:
        return None

    def noutrefresh(self) -> None:
        return None

    def move(self, *_args: object, **_kwargs: object) -> None:
        return None

    def clrtoeol(self) -> None:
        return None

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")


def _cfg() -> Config:
    cfg = Config()
    cfg.keys["quit"] = ["Q"]
    return cfg


def test_prompt_command_and_fzf_pick(monkeypatch: pytest.MonkeyPatch) -> None:
    screen = _Screen(keys=[ord("a"), ord("b"), curses.KEY_LEFT, curses.KEY_BACKSPACE, 9, 10])
    out = menus._prompt_command(screen, ["app", "apply"])
    assert out

    monkeypatch.setattr(menus, "fzf_enabled", lambda: True)
    monkeypatch.setattr(menus.curses, "def_prog_mode", lambda: None)
    monkeypatch.setattr(menus.curses, "endwin", lambda: None)
    monkeypatch.setattr(menus.curses, "reset_prog_mode", lambda: None)
    monkeypatch.setattr(menus, "resolve_executable", lambda _name: "fzf")
    monkeypatch.setattr(
        menus,
        "run_trusted",
        lambda *_a, **_k: types.SimpleNamespace(returncode=0, stdout="beta\n"),
    )
    assert menus._fzf_pick_option(_Screen(), ["alpha", "beta"]) == 1

    monkeypatch.setattr(
        menus,
        "run_trusted",
        lambda *_a, **_k: types.SimpleNamespace(returncode=1, stdout=""),
    )
    assert menus._fzf_pick_option(_Screen(), ["alpha", "beta"]) is None


def test_menu_internal_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(menus, "fzf_enabled", lambda: False)
    hint = menus._default_hint_provider(has_command=True)(0)
    assert ": cmd" in hint

    screen = _Screen()
    menu = menus.Menu(screen, "Title", ["one", "two"], disabled_indices={0})
    menu.display()
    assert any("Title" in line for line in screen.lines)

    action = menu._handle_navigation_key(ord(":"), _cfg())
    assert action == "command"
    assert menu._handle_navigation_key(ord("!"), _cfg()) == "terminal"
    assert menu._handle_navigation_key(ord("/"), _cfg()) == "search"
    assert menu._handle_navigation_key(ord("s"), _cfg()) == "global_search"
    assert menu._handle_navigation_key(ord("?"), _cfg()) == "continue"


def test_menu_navigate_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg()
    monkeypatch.setattr(menus, "get_config", lambda: cfg)
    monkeypatch.setattr(menus, "fzf_enabled", lambda: False)
    monkeypatch.setattr(menus.curses, "doupdate", lambda: None)
    monkeypatch.setattr(menus.curses, "color_pair", lambda value: value)
    monkeypatch.setattr(menus.curses, "beep", lambda: None)

    # command handler branch
    screen = _Screen(keys=[ord(":"), ord("h")])
    menu = menus.Menu(screen, "Title", ["one"], command_handler=lambda _cmd: None)
    monkeypatch.setattr(menus, "_prompt_command", lambda *_a, **_k: "check")
    assert menu.navigate() == -1

    # terminal + global search branch
    seen: list[str] = []
    screen = _Screen(keys=[ord("!"), ord("s"), ord("h")])
    menu = menus.Menu(screen, "Title", ["one"], command_handler=lambda cmd: seen.append(cmd) or None)
    assert menu.navigate() == -1
    assert seen[:2] == ["term", "search"]

    # disabled option branch
    screen = _Screen(keys=[10, ord("h")])
    menu = menus.Menu(
        screen,
        "Title",
        ["one", "back"],
        disabled_indices={0},
        disabled_reasons={0: "nope"},
    )
    monkeypatch.setattr(menus, "_show_help", lambda *_a, **_k: None)
    assert menu.navigate() == -1

    # submenu / root menu quick paths
    submenu = menus.Submenu(_Screen(keys=[ord("h")]), "Sub", ["one"])
    assert submenu.navigate() == -1
    root = menus.RootMenu(_Screen(keys=[ord("h")]), "Root", ["one"])
    assert root.navigate() == -1


def test_menu_quit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg()
    cfg.keys["quit"] = ["q"]
    monkeypatch.setattr(menus, "get_config", lambda: cfg)
    monkeypatch.setattr(menus, "fzf_enabled", lambda: False)
    menu = menus.Menu(_Screen(keys=[ord("q")]), "Title", ["one"])
    with pytest.raises(QuitAppError):
        menu.navigate()
