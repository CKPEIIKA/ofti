from __future__ import annotations

import threading
import types
from pathlib import Path

import pytest

from ofti.foam.config import Config
from ofti.ui_curses import entry_browser as eb
from ofti.ui_curses.entry_browser import BrowserCallbacks


class _Screen:
    def __init__(self, keys: list[int] | None = None, height: int = 24, width: int = 90) -> None:
        self._keys = list(keys or [])
        self.height = height
        self.width = width
        self.lines: list[str] = []

    def clear(self) -> None:
        self.lines.clear()

    def erase(self) -> None:
        self.lines.clear()

    def getmaxyx(self) -> tuple[int, int]:
        return (self.height, self.width)

    def addstr(self, *args: object) -> None:
        self.lines.append(str(args[-1]))

    def move(self, *_args: object) -> None:
        return None

    def refresh(self) -> None:
        return None

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")

    def derwin(self, *_args: object) -> _Screen:
        return self

    def noutrefresh(self) -> None:
        return None

    def attron(self, *_args: object, **_kwargs: object) -> None:
        return None

    def attroff(self, *_args: object, **_kwargs: object) -> None:
        return None


def _callbacks(messages: list[str], commands: list[str]) -> BrowserCallbacks:
    return BrowserCallbacks(
        show_message=lambda _s, text: messages.append(text),
        view_file=lambda _s, _path: messages.append("view"),
        prompt_command=lambda _s, _suggestions: ":check",
        command_suggestions=lambda _case: ["check"],
        handle_command=lambda _s, _case, _state, cmd: commands.append(cmd) or None,
        mode_status=lambda _state: "mode",
    )


def _cfg() -> Config:
    cfg = Config()
    cfg.keys["quit"] = ["Q"]
    cfg.enable_entry_cache = False
    cfg.enable_background_entry_crawl = False
    return cfg


def test_entry_browser_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(eb.curses, "doupdate", lambda: None)
    assert eb._search_entries(["alpha", "beta"], 0, "z") is None

    case = tmp_path / "case"
    case.mkdir()
    file_path = case / "system" / "controlDict"
    file_path.parent.mkdir()
    file_path.write_text("application simpleFoam;\n")

    messages: list[str] = []
    commands: list[str] = []
    callbacks = _callbacks(messages, commands)

    monkeypatch.setattr(eb, "get_config", _cfg)
    monkeypatch.setattr(eb, "status_message", lambda *_a, **_k: None)
    monkeypatch.setattr(eb, "list_keywords", lambda _path: ["application"])
    monkeypatch.setattr(
        eb,
        "get_entry_metadata",
        lambda *_a, **_k: ("simpleFoam", "word", [], ["comment"], ["info"], lambda _v: None),
    )
    monkeypatch.setattr(eb, "_entry_browser_inline_edit", lambda *_a, **_k: messages.append("inline"))
    monkeypatch.setattr(eb, "_entry_browser_external_edit", lambda *_a, **_k: False)
    monkeypatch.setattr(eb, "_entry_browser_help", lambda *_a, **_k: messages.append("help"))
    monkeypatch.setattr(eb, "_entry_browser_context_help", lambda *_a, **_k: messages.append("context"))
    monkeypatch.setattr(eb, "fzf_enabled", lambda: False)
    monkeypatch.setattr(eb, "prompt_input", lambda *_a, **_k: "app")

    screen = _Screen(keys=[ord("c"), ord("/"), ord("?"), ord("K"), ord(":"), ord("l"), ord("h")])
    eb.entry_browser_screen(screen, case, file_path, object(), callbacks)
    assert "help" in messages
    assert "context" in messages
    assert "inline" in messages
    assert commands == [":check"]


def test_entry_browser_external_and_fzf_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    file_path = case / "system" / "controlDict"
    file_path.parent.mkdir()
    file_path.write_text("application simpleFoam;\n")

    messages: list[str] = []
    commands: list[str] = []
    callbacks = _callbacks(messages, commands)
    monkeypatch.setattr(eb, "get_config", _cfg)
    monkeypatch.setattr(eb, "status_message", lambda *_a, **_k: None)
    monkeypatch.setattr(eb, "list_keywords", lambda _path: ["application"])
    monkeypatch.setattr(
        eb,
        "get_entry_metadata",
        lambda *_a, **_k: ("simpleFoam", "word", [], [], [], lambda _v: None),
    )
    monkeypatch.setattr(eb, "_entry_browser_external_edit", lambda *_a, **_k: True)
    monkeypatch.setattr(eb, "_entry_browser_inline_edit", lambda *_a, **_k: None)
    screen = _Screen(keys=[ord("o"), ord("h")])
    eb.entry_browser_screen(screen, case, file_path, object(), callbacks)

    monkeypatch.setattr(eb, "fzf_enabled", lambda: True)
    monkeypatch.setattr(eb.curses, "def_prog_mode", lambda: None)
    monkeypatch.setattr(eb.curses, "endwin", lambda: None)
    monkeypatch.setattr(eb.curses, "reset_prog_mode", lambda: None)
    monkeypatch.setattr(
        eb,
        "run_trusted",
        lambda *_a, **_k: types.SimpleNamespace(returncode=0, stdout="beta\n"),
    )
    assert eb._fzf_pick_entry_in_file(screen, ["alpha", "beta"]) == 1

    monkeypatch.setattr(eb, "run_trusted", lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError()))
    assert eb._fzf_pick_entry_in_file(screen, ["alpha", "beta"]) is None


def test_entry_browser_editor_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    file_path = case / "dict"
    file_path.write_text("x\n")
    messages: list[str] = []
    commands: list[str] = []
    callbacks = _callbacks(messages, commands)

    monkeypatch.setattr(eb, "read_entry", lambda *_a, **_k: " old ")
    monkeypatch.setattr(eb, "_open_in_external_editor", lambda *_a, **_k: " new ")
    called: list[str] = []
    monkeypatch.setattr(eb, "apply_assignment_or_write", lambda *_a, **_k: called.append("save") or True)
    monkeypatch.setattr(eb, "refresh_entry_cache", lambda *_a, **_k: called.append("refresh"))
    assert eb._entry_browser_external_edit(_Screen(), file_path, case, {}, "a", callbacks, True) is True
    assert called == ["save", "refresh"]

    class FakeEditor:
        def __init__(self, *_a, **_k) -> None:
            return None

        def edit(self) -> None:
            called.append("edit")

    monkeypatch.setattr(eb, "EntryEditor", FakeEditor)
    eb._entry_browser_inline_edit(
        _Screen(),
        file_path,
        case,
        {},
        "a",
        "value",
        lambda _v: None,
        "type",
        [],
        callbacks,
        True,
    )
    assert "edit" in called

    thread = eb._start_entry_crawl(file_path, ["a", "b"], {}, threading.Event())
    thread.join(timeout=1.0)
