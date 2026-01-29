
from ofti.ui_curses import entry_browser
from ofti.ui_curses.entry_browser import BrowserCallbacks


class DummyScreen:
    def clear(self) -> None:
        pass

    def refresh(self) -> None:
        pass


class DummyCallbacks:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def show_message(self, _stdscr, msg: str) -> None:
        self.messages.append(msg)


def _callbacks(dummy: DummyCallbacks) -> BrowserCallbacks:
    return BrowserCallbacks(
        show_message=dummy.show_message,
        view_file=lambda *_args, **_kwargs: None,
        prompt_command=lambda *_args, **_kwargs: "",
        command_suggestions=lambda *_args, **_kwargs: [],
        handle_command=lambda *_args, **_kwargs: None,
        mode_status=lambda *_args, **_kwargs: "",
    )


def test_open_in_external_editor(monkeypatch) -> None:
    screen = DummyScreen()
    callbacks = DummyCallbacks()
    monkeypatch.setenv("EDITOR", "true")
    monkeypatch.setattr(entry_browser, "resolve_executable", lambda cmd: cmd)
    monkeypatch.setattr(entry_browser, "run_trusted", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(entry_browser.curses, "endwin", lambda *_: None)
    result = entry_browser._open_in_external_editor(screen, "initial", _callbacks(callbacks))
    assert result is not None
