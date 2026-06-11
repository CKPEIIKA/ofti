"""Textual mission-control app.

Pure renderer: panel content and runtime-edit flows come from
``ofti.ui.deck``, which reuses the same services as the CLI and the
curses TUI.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import ClassVar, cast

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Grid, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Static, TabbedContent, TabPane

from ofti.foam.subprocess_utils import run_trusted
from ofti.ui import deck as deck_model

_SEVERITY_STYLES = {
    "crit": "bold red",
    "warn": "yellow",
    "ok": "green",
}

_NARROW_WIDTH = 100
_FLIGHT_ACTIONS = {"safe_stop", "write_now", "edit_delta_t", "edit_end_time"}

HELP_TEXT = """\
OFTI mission control — live deck over the shared case services.

Tabs
  Cockpit    case DNA, flight status, scopes, alerts, log radar
  Checklist  launch go/no-go gate
  Flight     live run state, criteria, runtime edits
  Analyze    log metrics + residual split
  Mesh       checkMesh radar
  Resources  disk growth / write-risk watch
  Doctor     case doctor + lint findings
  Fleet      live sibling cases

Keys
  1-8, h/l or ←/→   switch tab       Tab / Shift+Tab   move panel focus
  j/k g/G           scroll panel     r                 refresh now
  /                 filter panel…    :                 command palette
  !                 shell in case    ?                 this help
  q                 quit             Esc               close dialog

Flight tab runtime edits (diff preview, snapshot required before apply):
  s safe stop   w write now   d edit deltaT…   e edit endTime…

Dictionaries stay the source of truth; every runtime edit shows the
exact controlDict change and writes a case snapshot before applying.
Full case editing lives in the curses TUI (`ofti CASE`) and `ofti knife`.
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
        width: 76;
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


class PromptScreen(ModalScreen[str | None]):
    """One-line value prompt (new deltaT, search filter, ...)."""

    BINDINGS: ClassVar = [Binding("escape", "cancel_prompt", "Cancel")]

    CSS = """
    PromptScreen {
        align: center middle;
    }
    #prompt-box {
        border: round $accent;
        background: $surface;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    """

    def __init__(self, title: str, *, placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        box = VerticalScroll(
            Input(placeholder=self._placeholder, id="prompt-input"),
            id="prompt-box",
        )
        box.border_title = self._title
        yield box

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel_prompt(self) -> None:
        self.dismiss(None)


class RuntimeEditScreen(ModalScreen[bool]):
    """Diff preview -> snapshot-required apply -> result, all via shared services."""

    BINDINGS: ClassVar = [
        Binding("escape", "cancel_edit", "Cancel"),
        Binding("enter", "confirm_edit", "Snapshot + apply", priority=True),
    ]

    CSS = """
    RuntimeEditScreen {
        align: center middle;
    }
    #runtime-card {
        border: round $warning;
        border-title-align: center;
        background: $surface;
        padding: 1 2;
        width: 90;
        height: auto;
        max-height: 90%;
    }
    """

    def __init__(self, case_path: Path, updates: dict[str, str]) -> None:
        super().__init__()
        self.case_path = case_path
        self.updates = updates
        self.applied = False

    def compose(self) -> ComposeResult:
        card = VerticalScroll(Static("loading preview ...", id="runtime-body"), id="runtime-card")
        card.border_title = "Runtime edit — preview"
        card.border_subtitle = "[Enter] snapshot + apply   [Esc] cancel"
        yield card

    def on_mount(self) -> None:
        self._load_preview()

    @work(thread=True, exclusive=True, group="runtime-edit")
    def _load_preview(self) -> None:
        lines = deck_model.runtime_edit_preview(self.case_path, self.updates)
        self.app.call_from_thread(self._show, lines, applied=False)

    @work(thread=True, exclusive=True, group="runtime-edit")
    def _apply_edit(self) -> None:
        lines = deck_model.runtime_edit_apply(self.case_path, self.updates)
        self.app.call_from_thread(self._show, lines, applied=True)

    def _show(self, lines: list[str], *, applied: bool) -> None:
        self.applied = applied
        self.query_one("#runtime-body", Static).update(styled_lines(lines))
        card = self.query_one("#runtime-card", VerticalScroll)
        if applied:
            card.border_title = "Runtime edit — result"
            card.border_subtitle = "[Esc] close"

    def action_confirm_edit(self) -> None:
        if self.applied:
            self.dismiss(True)
            return
        self._apply_edit()

    def action_cancel_edit(self) -> None:
        self.dismiss(self.applied)


class DeckPanelView(VerticalScroll):
    """One bordered, scrollable deck panel with an optional line filter."""

    BINDINGS: ClassVar = [
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
    ]

    def __init__(self, panel: deck_model.DeckPanel) -> None:
        super().__init__(id=f"panel-{panel.panel_id}", classes="deck-panel")
        self.border_title = panel.title
        self._body = Static("loading ...", id=f"body-{panel.panel_id}")
        self._lines: list[str] = []
        self._filter = ""
        self._updated = ""

    def compose(self) -> ComposeResult:
        yield self._body

    def show_lines(self, lines: list[str], *, updated: str) -> None:
        self._lines = lines
        self._updated = updated
        self._render_lines()

    def set_filter(self, text: str) -> None:
        self._filter = text.strip()
        self._render_lines()

    def _render_lines(self) -> None:
        lines = self._lines
        subtitle = f"updated {self._updated}" if self._updated else ""
        if self._filter:
            needle = self._filter.lower()
            shown = [line for line in lines if needle in line.lower()]
            subtitle = f"filter:'{self._filter}' {len(shown)}/{len(lines)}  {subtitle}".strip()
            lines = shown or [f"no lines match '{self._filter}'"]
        self._body.update(styled_lines(lines))
        self.border_subtitle = subtitle


class DeckCommands(Provider):
    """Command palette entries for the deck (`:` or Ctrl+P)."""

    @property
    def _deck(self) -> MissionControlApp:
        return cast("MissionControlApp", self.app)

    def _commands(self) -> list[tuple[str, str, Callable[[], None]]]:
        app = self._deck
        rows: list[tuple[str, str, Callable[[], None]]] = [
            (f"Go to {label}", f"Open the {label} tab", partial(app.action_jump_tab, index))
            for index, (_tab_id, label) in enumerate(deck_model.DECK_TABS)
        ]
        rows += [
            ("Refresh deck", "Reload the active tab now", app.action_refresh_deck),
            ("Safe stop…", "stopAt writeNow with diff + snapshot", app.action_safe_stop),
            ("Write now…", "stopAt writeNow with diff + snapshot", app.action_write_now),
            ("Edit deltaT…", "controlDict edit with diff + snapshot", app.action_edit_delta_t),
            ("Edit endTime…", "controlDict edit with diff + snapshot", app.action_edit_end_time),
            ("Filter panel…", "Filter lines in the focused panel", app.action_search),
            ("Open shell in case directory", "Suspend the deck and run $SHELL", app.action_shell),
            ("Help", "Show keys and tab reference", app.action_show_help),
            ("Quit deck", "Exit mission control", app.action_quit_deck),
        ]
        return rows

    async def discover(self) -> Hits:
        for name, help_text, callback in self._commands():
            yield DiscoveryHit(name, callback, help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, help_text, callback in self._commands():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), callback, help=help_text)


class MissionControlApp(App[int]):
    """OFTI mission control: live deck over shared case services."""

    TITLE = "OFTI mission control"

    COMMANDS: ClassVar = {DeckCommands, *App.COMMANDS}

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
        Binding("slash", "search", "Filter"),
        Binding("colon", "command_palette", "Palette", show=False),
        Binding("exclamation_mark", "shell", "Shell", show=False),
        Binding("left,h", "previous_tab", "Prev tab", show=False),
        Binding("right,l", "next_tab", "Next tab", show=False),
        Binding("s", "safe_stop", "Safe stop…"),
        Binding("w", "write_now", "Write now…"),
        Binding("d", "edit_delta_t", "deltaT…"),
        Binding("e", "edit_end_time", "endTime…"),
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
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        del parameters
        if action in _FLIGHT_ACTIONS:
            return True if self.active_tab_id() == "flight" else None
        return True

    def active_tab_id(self) -> str:
        try:
            return str(self.query_one("#deck-tabs", TabbedContent).active or "cockpit")
        except Exception:
            return "cockpit"

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

    def _focused_panel(self) -> DeckPanelView | None:
        focused = self.focused
        while focused is not None:
            if isinstance(focused, DeckPanelView):
                return focused
            focused = focused.parent if hasattr(focused, "parent") else None
        panels = self.query(DeckPanelView)
        for view in panels:
            if view.id and self._panel_on_active_tab(view):
                return view
        return None

    def _panel_on_active_tab(self, view: DeckPanelView) -> bool:
        panel_id = (view.id or "").removeprefix("panel-")
        active_panels = deck_model.tab_panels(self.active_tab_id())
        return any(panel.panel_id == panel_id for panel in active_panels)

    # --- actions -------------------------------------------------------

    def action_refresh_deck(self) -> None:
        self.refresh_active_tab()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_quit_deck(self) -> None:
        self.exit(0)

    def action_search(self) -> None:
        panel = self._focused_panel()
        if panel is None:
            self.notify("No panel to filter here.", severity="warning")
            return

        def apply_filter(value: str | None) -> None:
            panel.set_filter(value or "")

        self.push_screen(
            PromptScreen(f"Filter {panel.border_title}", placeholder="substring, empty clears"),
            apply_filter,
        )

    def action_shell(self) -> None:
        shell = os.environ.get("SHELL") or "/bin/sh"
        try:
            with self.suspend():
                run_trusted([shell], cwd=self.case_path, capture_output=False)
        except Exception as exc:
            self.notify(f"Shell escape unavailable: {exc}", severity="warning")

    def action_safe_stop(self) -> None:
        self._runtime_edit(deck_model.flight_updates_for("safe-stop"))

    def action_write_now(self) -> None:
        self._runtime_edit(deck_model.flight_updates_for("write-now"))

    def action_edit_delta_t(self) -> None:
        self._prompt_runtime_value("deltaT")

    def action_edit_end_time(self) -> None:
        self._prompt_runtime_value("endTime")

    def _prompt_runtime_value(self, key: str) -> None:
        def submit(value: str | None) -> None:
            updates = deck_model.flight_updates_for(key, value)
            if updates:
                self._runtime_edit(updates)

        self.push_screen(PromptScreen(f"New {key}", placeholder="value"), submit)

    def _runtime_edit(self, updates: dict[str, str]) -> None:
        if not updates:
            return

        def done(applied: bool | None) -> None:
            if applied:
                self.notify("Runtime edit applied (snapshot written).")
            self.refresh_active_tab()

        self.push_screen(RuntimeEditScreen(self.case_path, updates), done)

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
