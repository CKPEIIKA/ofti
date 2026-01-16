"""Command line prompt behavior in menus."""

from of_tui.menus import Menu


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

    def move(self, *args, **kwargs) -> None:
        pass

    def clrtoeol(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("q")


def test_menu_command_prompt_tab_completion_cycles() -> None:
    captured: list[str] = []
    screen = FakeScreen(keys=[ord(":"), ord("t"), ord("o"), 9, 10])
    suggestions = ["tools", "tool blockMesh", "tool_dicts"]

    def handler(cmd: str) -> str:
        captured.append(cmd)
        return "quit"

    menu = Menu(
        screen,
        "Title",
        ["Only"],
        command_handler=handler,
        command_suggestions=lambda: suggestions,
    )

    menu.navigate()

    assert captured == ["tools"]
