import curses

from ofti.ui_curses.inputs import prompt_input


class FakeInputScreen:
    def __init__(self, keys: list[int]) -> None:
        self._keys = keys
        self._y = 0
        self._x = 0
        self.buffer = ""

    def addstr(self, text: str) -> None:
        self.buffer += text

    def refresh(self) -> None:
        pass

    def getyx(self):
        return (self._y, self._x)

    def getmaxyx(self):
        return (24, 80)

    def move(self, y: int, x: int) -> None:
        self._y = y
        self._x = x

    def clrtoeol(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return curses.KEY_ENTER


def test_prompt_input_collects_text(monkeypatch) -> None:
    keys = [ord("a"), ord("b"), ord("c"), curses.KEY_ENTER]
    screen = FakeInputScreen(keys)
    monkeypatch.setattr(curses, "curs_set", lambda *_: None)
    result = prompt_input(screen, "Prompt: ")
    assert result == "abc"


def test_prompt_input_esc_returns_none(monkeypatch) -> None:
    screen = FakeInputScreen([27])
    monkeypatch.setattr(curses, "curs_set", lambda *_: None)
    assert prompt_input(screen, "Prompt: ") is None
