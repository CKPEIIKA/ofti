"""UI-neutral mission-control deck model.

Maps deck tabs/panels to shared service line producers so any renderer
(curses, Textual, plain CLI) can show the same payloads without owning
case logic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.case_meta import case_metadata_quick
from ofti.tools import table_render_service
from ofti.tools.captains_deck_service import CaptainsDeckData, safe_lines
from ofti.tools.flight_deck_service import flight_deck_payload
from ofti.tools.launch_checklist_service import launch_checklist_payload
from ofti.tools.runtime_control_service import control_dict_edit_payload


@dataclass(frozen=True)
class DeckPanel:
    panel_id: str
    title: str
    tab_id: str


@dataclass(frozen=True)
class DeckUpdate:
    status: str
    panels: dict[str, list[str]]


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


def status_strip(case_path: Path) -> str:
    """One-line always-visible status: case, solver, run state, latest time.

    Uses quick metadata only so every refresh stays cheap.
    """
    try:
        meta = case_metadata_quick(case_path)
    except (OSError, RuntimeError, ValueError) as exc:
        return f"case:{case_path.name}  status unavailable: {exc}"
    parts = [
        f"case:{meta.get('case_name') or case_path.name}",
        meta.get("solver") or "solver:?",
        meta.get("status") or "?",
        f"t={meta.get('latest_time') or '-'}",
        f"np={meta.get('parallel') or '-'}",
        f"env:{meta.get('foam_version') or '?'}",
        f"log:{meta.get('log') or 'none'}",
    ]
    return "  ".join(parts)


def collect_deck_update(case_path: Path, tab_id: str) -> DeckUpdate:
    return DeckUpdate(
        status=status_strip(case_path),
        panels=collect_tab_lines(case_path, tab_id),
    )


# Runtime flight actions shared by curses and Textual flight decks.
RUNTIME_ACTIONS: tuple[tuple[str, str, bool], ...] = (
    # (action id, label, needs a value prompt)
    ("safe-stop", "Safe stop (stopAt writeNow)", False),
    ("write-now", "Write now (stopAt writeNow)", False),
    ("deltaT", "Edit deltaT", True),
    ("endTime", "Edit endTime", True),
)


def flight_updates_for(action: str, value: str | None = None) -> dict[str, str]:
    """Map a flight action id to safe controlDict updates."""
    normalized = action.strip().lower().replace("_", "-")
    if normalized in {"safe-stop", "write-now", "s", "w"}:
        return {"stopAt": "writeNow"}
    if normalized in {"deltat", "delta-t", "dt"}:
        return {"deltaT": value.strip()} if value and value.strip() else {}
    if normalized in {"endtime", "end-time", "e"}:
        return {"endTime": value.strip()} if value and value.strip() else {}
    return {}


def runtime_edit_preview(case_path: Path, updates: dict[str, str]) -> list[str]:
    return control_edit_lines(control_dict_edit_payload(case_path, updates))


def runtime_edit_apply(case_path: Path, updates: dict[str, str]) -> list[str]:
    return control_edit_lines(
        control_dict_edit_payload(case_path, updates, write_snapshot=True, apply=True),
    )


def control_edit_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = [
        "Runtime controlDict edit",
        f"case={payload.get('case')}",
        f"path={payload.get('path')}",
        f"ok={payload.get('ok')}",
        f"applied={payload.get('applied')}",
        f"blocked={payload.get('blocked')}",
    ]
    if payload.get("snapshot_path"):
        lines.append(f"snapshot={payload['snapshot_path']}")
    if payload.get("error"):
        lines.append(f"error={payload['error']}")
    updates = list(payload.get("updates") or [])
    if updates:
        lines.append("updates:")
        for row in updates:
            if isinstance(row, dict):
                old = row.get("old")
                new = row.get("new")
                lines.append(f"- {row.get('path')}:{row.get('key')} {old} -> {new}")
    diff = list(payload.get("diff") or [])
    if diff:
        lines.extend(["", "diff:", *[str(line) for line in diff]])
    failures = list(payload.get("failures") or [])
    if failures:
        lines.append(f"failures={', '.join(str(item) for item in failures)}")
    return lines


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
