from ofti.app.state import AppState, Screen
from ofti.ui.adapter import CursesAdapter
from ofti.ui.router import ScreenRouter


class DummyScreen:
    def __init__(self) -> None:
        self.calls = []

    def clear(self) -> None:
        self.calls.append("clear")

    def refresh(self) -> None:
        self.calls.append("refresh")

    def addstr(self, *_args, **_kwargs) -> None:
        self.calls.append("addstr")

    def getch(self) -> int:
        self.calls.append("getch")
        return 0

    def getmaxyx(self):
        return (24, 80)


def test_curses_adapter_passthrough() -> None:
    dummy = DummyScreen()
    adapter = CursesAdapter(dummy)
    adapter.clear()
    adapter.refresh()
    adapter.addstr("hi")
    adapter.getch()
    adapter.getmaxyx()
    assert "clear" in dummy.calls
    assert "refresh" in dummy.calls


def test_screen_router_dispatch() -> None:
    state = AppState()
    dummy = DummyScreen()
    router = ScreenRouter(
        handlers={Screen.MAIN_MENU: lambda _s, _c, _st: Screen.TOOLS},
    )
    assert router.dispatch(Screen.MAIN_MENU, dummy, None, state) == Screen.TOOLS
    assert router.dispatch(None, dummy, None, state) is None
    assert router.dispatch(Screen.SEARCH, dummy, None, state) == Screen.MAIN_MENU
