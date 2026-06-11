"""UI-neutral mission-control deck model.

Maps deck tabs/panels to shared service line producers so any renderer
(curses, Textual, plain CLI) can show the same payloads without owning
case logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ofti.tools import table_render_service
from ofti.tools.captains_deck_service import CaptainsDeckData, safe_lines
from ofti.tools.flight_deck_service import flight_deck_payload
from ofti.tools.launch_checklist_service import launch_checklist_payload


@dataclass(frozen=True)
class DeckPanel:
    panel_id: str
    title: str
    tab_id: str


DECK_TABS: tuple[tuple[str, str], ...] = (
    ("cockpit", "Cockpit"),
    ("checklist", "Checklist"),
    ("flight", "Flight"),
    ("analyze", "Analyze"),
    ("mesh", "Mesh"),
    ("resources", "Resources"),
    ("doctor", "Doctor"),
    ("fleet", "Fleet"),
)

DECK_PANELS: tuple[DeckPanel, ...] = (
    DeckPanel("dna", "Case DNA", "cockpit"),
    DeckPanel("status", "Flight status", "cockpit"),
    DeckPanel("scopes", "Mission scopes", "cockpit"),
    DeckPanel("alerts", "Alerts", "cockpit"),
    DeckPanel("log", "Log radar", "cockpit"),
    DeckPanel("checklist", "Launch checklist", "checklist"),
    DeckPanel("flightdeck", "Flight deck", "flight"),
    DeckPanel("eta", "ETA", "flight"),
    DeckPanel("logsplit", "Log + residuals", "analyze"),
    DeckPanel("meshradar", "Mesh radar", "mesh"),
    DeckPanel("resourcewatch", "Resource watch", "resources"),
    DeckPanel("doctor", "Case doctor", "doctor"),
    DeckPanel("lint", "Case lint", "doctor"),
    DeckPanel("fleet", "Live cases", "fleet"),
)


def tab_panels(tab_id: str) -> tuple[DeckPanel, ...]:
    return tuple(panel for panel in DECK_PANELS if panel.tab_id == tab_id)


def panel_lines(deck: CaptainsDeckData, panel_id: str) -> list[str]:
    case_path = deck.case_path
    producers = {
        "dna": deck.case_dna_lines,
        "status": deck.status_lines,
        "scopes": deck.scope_lines,
        "alerts": deck.alert_lines,
        "log": deck.folded_log_lines,
        "checklist": lambda: table_render_service.launch_checklist_table_lines(
            launch_checklist_payload(case_path),
        ),
        "flightdeck": lambda: table_render_service.flight_deck_table_lines(
            flight_deck_payload(case_path),
        ),
        "eta": deck.eta_lines,
        "logsplit": deck.log_residual_split_lines,
        "meshradar": deck.mesh_radar_lines,
        "resourcewatch": deck.resource_watch_lines,
        "doctor": deck.doctor_lines,
        "lint": deck.lint_lines,
        "fleet": deck.live_cases_lines,
    }
    return safe_lines(producers.get(panel_id, lambda: [f"unknown panel: {panel_id}"]))


def collect_tab_lines(case_path: Path, tab_id: str) -> dict[str, list[str]]:
    """Build all panel lines for one tab with a shared payload cache."""
    deck = CaptainsDeckData(case_path)
    return {panel.panel_id: panel_lines(deck, panel.panel_id) for panel in tab_panels(tab_id)}


_CRIT_TOKENS = ("CRIT", "FAIL", "NO-GO", "error", "Error", "✖")
_WARN_TOKENS = ("WARN", "warning", "stale", "unavailable", "missing", "▲")
_OK_TOKENS = ("OK", "PASS", "GO", "ready", "✓")


def line_severity(line: str) -> str | None:
    """Classify a rendered service line for renderer-side styling."""
    if any(token in line for token in _CRIT_TOKENS):
        return "crit"
    if any(token in line for token in _WARN_TOKENS):
        return "warn"
    if any(token in line for token in _OK_TOKENS):
        return "ok"
    return None
