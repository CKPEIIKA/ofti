from ofti.ui_curses import entry_browser


class FakeScreen:
    def __init__(self, height: int = 24, width: int = 80) -> None:
        self._height = height
        self._width = width

    def getmaxyx(self):
        return (self._height, self._width)


def test_entry_browser_scroll() -> None:
    screen = FakeScreen(height=10)
    scroll = entry_browser._entry_browser_scroll(0, 0, screen, total=100)
    assert scroll == 0
    scroll = entry_browser._entry_browser_scroll(50, 0, screen, total=100)
    assert scroll >= 0


def test_search_entries_wraps() -> None:
    keys = ["alpha", "beta", "gamma"]
    idx = entry_browser._search_entries(keys, 1, "alp", direction=1)
    assert idx == 0
