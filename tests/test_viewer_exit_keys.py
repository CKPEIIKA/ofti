from ofti.ui_curses.viewer import Viewer


class FakeScreen:
    def __init__(self, keys) -> None:
        self._keys = list(keys)
        self.output: list[str] = []

    def erase(self) -> None:
        pass

    def getmaxyx(self):
        return (10, 40)

    def addstr(self, *args, **_kwargs) -> None:
        if args:
            self.output.append(str(args[-1]))

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("q")


def test_viewer_exits_on_q() -> None:
    screen = FakeScreen(keys=[ord("q")])
    viewer = Viewer(screen, "hello")
    viewer.display()
    assert any("hello" in line for line in screen.output)


def test_viewer_exits_on_h() -> None:
    screen = FakeScreen(keys=[ord("h")])
    viewer = Viewer(screen, "hello")
    viewer.display()
    assert any("hello" in line for line in screen.output)
