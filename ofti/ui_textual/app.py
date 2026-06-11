"""Textual mission-control app.

Pure renderer: panel content comes from ``ofti.ui.deck`` line producers,
which reuse the same services as the CLI and the curses TUI.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, VerticalScroll
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from ofti.ui import deck as deck_model

_SEVERITY_STYLES = {
    "crit": "bold red",
    "warn": "yellow",
    "ok": "green",
}


def styled_lines(lines: list[str]) -> Text:
    text = Text()
    for line in lines:
        severity = deck_model.line_severity(line)
        text.append(line, style=_SEVERITY_STYLES.get(severity or "", ""))
        text.append("\n")
    return text


class DeckPanelView(VerticalScroll):
    """One bordered, scrollable deck panel."""

    def __init__(self, panel: deck_model.DeckPanel) -> None:
        super().__init__(id=f"panel-{panel.panel_id}", classes="deck-panel")
        self.border_title = panel.title
        self._body = Static("loading ...", id=f"body-{panel.panel_id}")

    def compose(self) -> ComposeResult:
        yield self._body

    def show_lines(self, lines: list[str]) -> None:
        self._body.update(styled_lines(lines))


class MissionControlApp(App[int]):
    """OFTI mission control: live deck over shared case services."""

    TITLE = "OFTI mission control"

    CSS = """
    .deck-panel {
        border: round $primary;
        padding: 0 1;
        height: 1fr;
    }
    #cockpit-grid {
        layout: grid;
        grid-size: 3;
        grid-rows: auto 1fr 12;
        grid-columns: 1fr 1fr 1fr;
    }
    #panel-dna {
        column-span: 3;
        height: auto;
        max-height: 14;
    }
    #panel-log {
        column-span: 3;
    }
    TabPane {
        padding: 0;
    }
    """

    BINDINGS: ClassVar = [
        Binding("q", "quit_deck", "Quit"),
        Binding("r", "refresh_deck", "Refresh"),
        Binding("left", "previous_tab", "Prev tab", show=False),
        Binding("right", "next_tab", "Next tab", show=False),
    ]

    def __init__(self, case_path: Path, *, interval: float = 3.0) -> None:
        super().__init__()
        self.case_path = case_path
        self.interval = interval
        self.sub_title = str(case_path)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="cockpit", id="deck-tabs"):
            for tab_id, label in deck_model.DECK_TABS:
                with TabPane(label, id=tab_id):
                    panels = deck_model.tab_panels(tab_id)
                    if tab_id == "cockpit":
                        with Grid(id="cockpit-grid"):
                            for panel in panels:
                                yield DeckPanelView(panel)
                    else:
                        for panel in panels:
                            yield DeckPanelView(panel)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_active_tab()
        if self.interval > 0:
            self.set_interval(self.interval, self.refresh_active_tab)

    def on_tabbed_content_tab_activated(self, _event: TabbedContent.TabActivated) -> None:
        self.refresh_active_tab()

    def active_tab_id(self) -> str:
        return str(self.query_one("#deck-tabs", TabbedContent).active or "cockpit")

    def refresh_active_tab(self) -> None:
        self._collect_lines(self.active_tab_id())

    @work(thread=True, exclusive=True, group="deck-refresh")
    def _collect_lines(self, tab_id: str) -> None:
        results = deck_model.collect_tab_lines(self.case_path, tab_id)
        self.call_from_thread(self._apply_lines, results)

    def _apply_lines(self, results: dict[str, list[str]]) -> None:
        for panel_id, lines in results.items():
            try:
                view = self.query_one(f"#panel-{panel_id}", DeckPanelView)
            except Exception:
                continue
            view.show_lines(lines)

    def action_refresh_deck(self) -> None:
        self.refresh_active_tab()

    def action_quit_deck(self) -> None:
        self.exit(0)

    def action_previous_tab(self) -> None:
        self._step_tab(-1)

    def action_next_tab(self) -> None:
        self._step_tab(1)

    def _step_tab(self, step: int) -> None:
        tab_ids = [tab_id for tab_id, _ in deck_model.DECK_TABS]
        current = self.active_tab_id()
        index = tab_ids.index(current) if current in tab_ids else 0
        self.query_one("#deck-tabs", TabbedContent).active = tab_ids[
            (index + step) % len(tab_ids)
        ]


def run_mission_control(case_path: Path, *, interval: float = 3.0) -> int:
    app = MissionControlApp(case_path, interval=interval)
    result = app.run()
    return int(result or 0)
