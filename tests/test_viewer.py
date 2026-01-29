import curses

from ofti.ui_curses.viewer import Viewer


class FakeViewerScreen:
    def __init__(self, keys, inputs=None) -> None:
        self._keys = list(keys)
        self._inputs = [s.encode() for s in (inputs or [])]

    def erase(self) -> None:
        pass

    def clear(self) -> None:
        pass

    def getmaxyx(self):
        return (10, 80)

    def addstr(self, *args, **kwargs) -> None:
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")

    def getstr(self):
        if self._inputs:
            return self._inputs.pop(0)
        return b""


def test_viewer_display_exits_on_back(monkeypatch) -> None:
    _ = monkeypatch
    screen = FakeViewerScreen(keys=[ord("h")])
    viewer = Viewer(screen, "line1\nline2")
    viewer.display()


def test_viewer_search(monkeypatch) -> None:
    monkeypatch.setattr(curses, "echo", lambda *_: None)
    monkeypatch.setattr(curses, "noecho", lambda *_: None)
    screen = FakeViewerScreen(keys=[ord("/"), ord("h")], inputs=["line2"])
    viewer = Viewer(screen, "line1\nline2\nline3")
    viewer.display()
