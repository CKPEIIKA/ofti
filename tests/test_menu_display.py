from of_tui.menus import Menu


class FakeScreen:
    def __init__(self, width: int = 20, height: int = 10) -> None:
        self.width = width
        self.height = height
        self.lines = []

    def clear(self) -> None:
        self.lines.clear()

    def getmaxyx(self):
        return (self.height, self.width)

    def addstr(self, *args) -> None:
        # Record what would be printed; mimic simple line behavior.
        text = args[-1]
        self.lines.append(str(text))

    def attron(self, *args, **kwargs) -> None:  # pragma: no cover - unused in logic
        pass

    def attroff(self, *args, **kwargs) -> None:  # pragma: no cover - unused in logic
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        # Not used in these tests.
        return -1


def test_menu_display_truncates_long_options() -> None:
    screen = FakeScreen(width=10)
    options = ["very-long-option-name"]
    menu = Menu(screen, "Title", options)

    menu.display()

    # All printed lines should respect the screen width.
    for line in screen.lines:
        assert len(line.rstrip("\n")) <= screen.width
