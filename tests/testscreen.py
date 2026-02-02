from __future__ import annotations


class TestScreen:
    """Minimal curses-like screen for tests."""

    def __init__(self, keys=None, inputs=None, width=80, height=24) -> None:
        self._keys = list(keys or [])
        self._inputs = list(inputs or [])
        self._input_buffer: list[int] = []
        self._width = width
        self._height = height
        self.lines: list[str] = []
        self._timeout: int | None = None

    def clear(self) -> None:
        self.lines.clear()

    def erase(self) -> None:
        self.lines.clear()

    def getmaxyx(self):
        return (self._height, self._width)

    def getyx(self):
        return (0, 0)

    def addstr(self, *args, **_kwargs) -> None:
        text = args[-1] if args else ""
        self.lines.append(str(text))

    def attron(self, *_args, **_kwargs) -> None:
        pass

    def attroff(self, *_args, **_kwargs) -> None:
        pass

    def refresh(self) -> None:
        pass

    def move(self, *_args, **_kwargs) -> None:
        pass

    def clrtoeol(self) -> None:
        pass

    def timeout(self, value: int) -> None:
        self._timeout = value

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        if self._input_buffer:
            return self._input_buffer.pop(0)
        if self._inputs:
            text = self._inputs.pop(0)
            self._input_buffer = [*map(ord, text), 10]
            return self._input_buffer.pop(0)
        return ord("h")

    def getstr(self):
        if self._inputs:
            return self._inputs.pop(0).encode()
        return b""
