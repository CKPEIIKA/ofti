"""Menu navigation behavior for back/quit keys."""

from ofti.foam.config import Config
from ofti.ui_curses.menus import Menu, RootMenu


class FakeScreen:
    def __init__(self, keys) -> None:
        self._keys = list(keys)
        self.height = 24
        self.width = 80
        self.lines = []

    def clear(self) -> None:
        self.lines.clear()

    def getmaxyx(self):
        return (self.height, self.width)

    def addstr(self, *args) -> None:
        self.lines.append(str(args[-1]))

    def attron(self, *args, **kwargs) -> None:
        pass

    def attroff(self, *args, **kwargs) -> None:
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("q")


def test_menu_back_with_h_returns_minus_one() -> None:
    screen = FakeScreen(keys=[ord("h")])
    menu = Menu(screen, "Title", ["Only"])
    assert menu.navigate() == -1


def test_root_menu_back_with_h_returns_minus_one() -> None:
    screen = FakeScreen(keys=[ord("h")])
    menu = RootMenu(screen, "Title", ["Only"])
    assert menu.navigate() == -1


def test_menu_search_selects_option(monkeypatch) -> None:
    screen = FakeScreen(keys=[ord("/"), ord("h")])
    menu = Menu(screen, "Title", ["alpha", "beta"])
    monkeypatch.setattr("ofti.ui_curses.menus._fzf_pick_option", lambda *_: 1)
    assert menu.navigate() == -1
    assert menu.current_option == 1


def test_menu_global_search_invokes_command() -> None:
    cfg = Config()
    cfg.keys["global_search"] = ["s"]
    menu = Menu(FakeScreen(keys=[]), "Title", ["alpha"])
    assert menu._handle_navigation_key(ord("s"), cfg) == "global_search"
