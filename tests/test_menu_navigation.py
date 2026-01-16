"""Menu navigation behavior for back/quit keys."""

from of_tui.menus import Menu, RootMenu


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
