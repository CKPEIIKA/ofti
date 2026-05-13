from __future__ import annotations

from pathlib import Path

from ofti.app.screens import cockpit
from ofti.app.state import AppState, Screen


class _Screen:
    def __init__(self, keys: list[int]) -> None:
        self.keys = list(keys)
        self.lines: list[str] = []

    def getmaxyx(self) -> tuple[int, int]:
        return (20, 90)

    def erase(self) -> None:
        self.lines.clear()

    def addstr(self, *args) -> None:
        text = str(args[-1])
        self.lines.append(text)

    def refresh(self) -> None:
        return

    def getch(self) -> int:
        if self.keys:
            return self.keys.pop(0)
        return ord("q")

    def attron(self, *_args) -> None:
        return

    def attroff(self, *_args) -> None:
        return


def test_captains_deck_screen_menu_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cockpit, "cockpit_lines", lambda *_a, **_k: ["OFTI CAPTAINS DECK"])
    monkeypatch.setattr(cockpit, "draw_status_bar", lambda *_a, **_k: None)

    screen = _Screen([ord("m")])
    result = cockpit.cockpit_screen(screen, tmp_path, AppState())

    assert result == Screen.MAIN_MENU
    assert "OFTI CAPTAINS DECK" in "\n".join(screen.lines)


def test_captains_deck_screen_quit_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cockpit, "cockpit_lines", lambda *_a, **_k: ["OFTI CAPTAINS DECK"])
    monkeypatch.setattr(cockpit, "draw_status_bar", lambda *_a, **_k: None)

    assert cockpit.cockpit_screen(_Screen([ord("q")]), tmp_path, AppState()) is None


def test_captains_deck_screen_opens_selected_panel_detail(monkeypatch, tmp_path: Path) -> None:
    opened: list[str] = []

    class _Viewer:
        def __init__(self, _stdscr, content: str) -> None:
            opened.append(content)

        def display(self) -> None:
            return

    monkeypatch.setattr(cockpit, "cockpit_lines", lambda *_a, **_k: ["OFTI CAPTAINS DECK"])
    monkeypatch.setattr(cockpit, "draw_status_bar", lambda *_a, **_k: None)
    monkeypatch.setattr(cockpit, "cockpit_panel_names", lambda: ["Flight", "Alerts"])
    monkeypatch.setattr(cockpit, "cockpit_panel_detail_lines", lambda *_a: ["detail"])
    monkeypatch.setattr(cockpit, "Viewer", _Viewer)

    result = cockpit.cockpit_screen(_Screen([ord("l"), 10, ord("m")]), tmp_path, AppState())

    assert result == Screen.MAIN_MENU
    assert opened
    assert opened[0].startswith("Alerts")
