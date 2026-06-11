"""Textual mission-control app.

Pure renderer: panel content comes from ``ofti.ui.deck`` line producers,
which reuse the same services as the CLI and the curses TUI.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from ofti.ui import deck as deck_model

_SEVERITY_STYLES = {
    "crit": "bold red",
    "warn": "yellow",
    "ok": "green",
}

_NARROW_WIDTH = 100

HELP_TEXT = """\
OFTI mission control — read-only deck over the shared case services.

Tabs
  Cockpit    case DNA, flight status, scopes, alerts, log radar
  Checklist  launch go/no-go gate
  Flight     live run state, criteria, runtime queue preview
  Analyze    log metrics + residual split
  Mesh       checkMesh radar
  Resources  disk growth / write-risk watch
  Doctor     case doctor + lint findings
  Fleet      live sibling cases

Keys
  1-8 or ←/→   switch tab        Tab / Shift+Tab   move panel focus
  r            refresh now       q                 quit
  ?            this help         Esc               close help
  ctrl+p       command palette

The deck never edits the case; dictionaries stay the source of truth.
Edits go through the curses TUI (`ofti CASE`) or `ofti knife ...`.
"""


def styled_lines(lines: list[str]) -> Text:
    text = Text()
    for line in lines:
        severity = deck_model.line_severity(line)
        text.append(line, style=_SEVERITY_STYLES.get(severity or "", ""))
        text.append("\n")
    return text


class HelpScreen(ModalScreen[None]):
    BINDINGS: ClassVar = [
        Binding("escape,question_mark,q", "close_help", "Close"),
    ]

    CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-card {
        border: round $accent;
        border-title-align: center;
        background: $surface;
        padding: 1 2;
        width: 72;
        height: auto;
        max-height: 90%;
    }
    """

    def compose(self) -> ComposeResult:
        card = Static(HELP_TEXT, id="help-card")
        card.border_title = "Help"
        yield card

    def action_close_help(self) -> None:
        self.dismiss()


class DeckPanelView(VerticalScroll):
    """One bordered, scrollable deck panel."""

    def __init__(self, panel: deck_model.DeckPanel) -> None:
        super().__init__(id=f"panel-{panel.panel_id}", classes="deck-panel")
        self.border_title = panel.title
        self._body = Static("loading ...", id=f"body-{panel.panel_id}")

    def compose(self) -> ComposeResult:
        yield self._body

    def show_lines(self, lines: list[str], *, updated: str) -> None:
        self._body.update(styled_lines(lines))
        self.border_subtitle = f"updated {updated}"


class MissionControlApp(App[int]):
    """OFTI mission control: live deck over shared case services."""

    TITLE = "OFTI mission control"

    CSS = """
    #status-bar {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text;
        text-style: bold;
    }
    .deck-panel {
        border: round $primary;
        padding: 0 1;
        height: 1fr;
    }
    .deck-panel:focus {
        border: round $accent;
    }
    #cockpit-grid {
        layout: grid;
        grid-size: 3;
        grid-rows: auto 1fr 12;
        grid-columns: 1fr 1fr 1fr;
    }
    #cockpit-grid.narrow {
        grid-size: 1;
        grid-rows: auto;
    }
    #panel-dna {
        column-span: 3;
        height: auto;
        max-height: 14;
    }
    #panel-log {
        column-span: 3;
    }
    #cockpit-grid.narrow #panel-dna,
    #cockpit-grid.narrow #panel-log {
        column-span: 1;
    }
    #cockpit-grid.narrow .deck-panel {
        height: auto;
        max-height: 16;
    }
    TabPane {
        padding: 0;
    }
    """

    BINDINGS: ClassVar = [
        Binding("q", "quit_deck", "Quit"),
        Binding("r", "refresh_deck", "Refresh"),
        Binding("question_mark", "show_help", "Help"),
        Binding("left", "previous_tab", "Prev tab", show=False),
        Binding("right", "next_tab", "Next tab", show=False),
        *[
            Binding(str(slot + 1), f"jump_tab({slot})", "Tab", show=False)
            for slot in range(len(deck_model.DECK_TABS))
        ],
    ]

    def __init__(self, case_path: Path, *, interval: float = 3.0) -> None:
        super().__init__()
        self.case_path = case_path
        self.interval = interval
        self.sub_title = str(case_path)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(f"case:{self.case_path.name}  loading ...", id="status-bar")
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

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#cockpit-grid", Grid).set_class(
            event.size.width < _NARROW_WIDTH,
            "narrow",
        )

    def on_tabbed_content_tab_activated(self, _event: TabbedContent.TabActivated) -> None:
        self.refresh_active_tab()

    def active_tab_id(self) -> str:
        return str(self.query_one("#deck-tabs", TabbedContent).active or "cockpit")

    def refresh_active_tab(self) -> None:
        self._collect_update(self.active_tab_id())

    @work(thread=True, exclusive=True, group="deck-refresh")
    def _collect_update(self, tab_id: str) -> None:
        update = deck_model.collect_deck_update(self.case_path, tab_id)
        self.call_from_thread(self._apply_update, update)

    def _apply_update(self, update: deck_model.DeckUpdate) -> None:
        self.query_one("#status-bar", Static).update(update.status)
        stamp = datetime.now().astimezone().strftime("%H:%M:%S")
        for panel_id, lines in update.panels.items():
            try:
                view = self.query_one(f"#panel-{panel_id}", DeckPanelView)
            except Exception:
                continue
            view.show_lines(lines, updated=stamp)

    def action_refresh_deck(self) -> None:
        self.refresh_active_tab()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_quit_deck(self) -> None:
        self.exit(0)

    def action_previous_tab(self) -> None:
        self._step_tab(-1)

    def action_next_tab(self) -> None:
        self._step_tab(1)

    def action_jump_tab(self, index: int) -> None:
        tab_ids = [tab_id for tab_id, _ in deck_model.DECK_TABS]
        if 0 <= index < len(tab_ids):
            self.query_one("#deck-tabs", TabbedContent).active = tab_ids[index]

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
