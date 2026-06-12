"""UI-neutral mission-control deck model.

Maps deck tabs/panels to shared service line producers so any renderer
(curses, Textual, plain CLI) can show the same payloads without owning
case logic.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.case_meta import case_metadata_quick
from ofti.foam.openfoam_env import environment_loaded, resolve_openfoam_bashrc
from ofti.tools import table_render_service
from ofti.tools.captains_deck_service import CaptainsDeckData, safe_lines
from ofti.tools.flight_deck_service import flight_deck_payload
from ofti.tools.launch_checklist_service import launch_checklist_payload
from ofti.tools.process_scan_service import is_case_dir, scan_proc_solver_processes
from ofti.tools.runtime_control_service import control_dict_edit_payload


@dataclass(frozen=True)
class DeckPanel:
    panel_id: str
    title: str
    tab_id: str
    description: str


@dataclass(frozen=True)
class DeckUpdate:
    status: str
    panels: dict[str, list[str]]


@dataclass(frozen=True)
class CaseCandidate:
    label: str
    path: Path
    kind: str  # current | running | nearby


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
    DeckPanel(
        "dna",
        "Case DNA",
        "cockpit",
        "Identity card: solver, run state, fields/patches, risk, setup fingerprint.",
    ),
    DeckPanel(
        "status",
        "Flight status",
        "cockpit",
        "Live run state from the solver log: jobs, latest time, dt, ETA, criteria.",
    ),
    DeckPanel(
        "scopes",
        "Mission scopes",
        "cockpit",
        "Telemetry from the latest log: Courant, sec/iter, residuals (sparklines).",
    ),
    DeckPanel(
        "alerts",
        "Alerts",
        "cockpit",
        "Interpreted warnings with impact, evidence, and suggested action.",
    ),
    DeckPanel(
        "log",
        "Log radar",
        "cockpit",
        "Bounded solver log tail with repeated solver lines folded away.",
    ),
    DeckPanel(
        "checklist",
        "Launch checklist",
        "checklist",
        "Go / no-go gate before launching: case, mesh, numerics, parallel, monitors.",
    ),
    DeckPanel(
        "flightdeck",
        "Flight deck",
        "flight",
        "Runtime controls and stop criteria; s/w/d/e stage safe controlDict edits.",
    ),
    DeckPanel(
        "eta",
        "ETA",
        "flight",
        "Time-to-endTime and time-to-criteria estimates from log progress.",
    ),
    DeckPanel(
        "logsplit",
        "Log + residuals",
        "analyze",
        "Log metrics next to per-field residual history from the same window.",
    ),
    DeckPanel(
        "meshradar",
        "Mesh radar",
        "mesh",
        "checkMesh quality metrics with warning bars and numerics advice.",
    ),
    DeckPanel(
        "resourcewatch",
        "Resource watch",
        "resources",
        "Disk growth, time-directory count, write-risk settings, ETA to disk-full.",
    ),
    DeckPanel(
        "doctor",
        "Case doctor",
        "doctor",
        "Setup findings: missing dictionaries, pressure reference, decomposition.",
    ),
    DeckPanel(
        "lint",
        "Case lint",
        "doctor",
        "Lint findings with evidence and advice (same data as `ofti knife lint`).",
    ),
    DeckPanel(
        "fleet",
        "Live cases",
        "fleet",
        "Sibling cases next to this one: state, latest time, quick comparison.",
    ),
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


def env_status() -> tuple[bool, str]:
    """OpenFOAM environment state for status displays.

    Returns (loaded, label); label names the version or sourced bashrc.
    """
    loaded = environment_loaded()
    if not loaded:
        return False, "env not loaded ▲"
    detail = os.environ.get("WM_PROJECT_VERSION") or os.environ.get("FOAM_VERSION")
    if not detail:
        bashrc = resolve_openfoam_bashrc()
        if bashrc is not None:
            detail = bashrc.parent.parent.name
    return True, f"env {detail or 'detected'} ✓"


def status_strip(case_path: Path) -> str:
    """One-line always-visible status: case, solver, run state, env, latest time.

    Uses quick metadata only so every refresh stays cheap. Segments are
    separated by two spaces so renderers can style them independently.
    """
    _loaded, env_label = env_status()
    if not is_case_dir(case_path):
        return (
            f"case:{case_path.name} not an OpenFOAM case ▲  {env_label}  "
            "press c to choose a case"
        )
    try:
        meta = case_metadata_quick(case_path)
    except (OSError, RuntimeError, ValueError) as exc:
        return f"case:{case_path.name}  status unavailable: {exc}  {env_label}"
    parts = [
        f"case:{meta.get('case_name') or case_path.name}",
        meta.get("solver") or "solver:?",
        meta.get("status") or "?",
        f"t={meta.get('latest_time') or '-'}",
        f"np={meta.get('parallel') or '-'}",
        env_label,
        f"log:{meta.get('log') or 'none'}",
    ]
    return "  ".join(parts)


def collect_deck_update(case_path: Path, tab_id: str) -> DeckUpdate:
    if not is_case_dir(case_path):
        placeholder = [
            "Not an OpenFOAM case directory (no system/controlDict).",
            "",
            "Press c to choose a case, or run: ofti tui CASE",
        ]
        panels = {panel.panel_id: list(placeholder) for panel in tab_panels(tab_id)}
        return DeckUpdate(status=status_strip(case_path), panels=panels)
    return DeckUpdate(
        status=status_strip(case_path),
        panels=collect_tab_lines(case_path, tab_id),
    )


def case_candidates(start_path: Path, *, nearby_limit: int = 30) -> list[CaseCandidate]:
    """Chooser entries: current case, visible running cases, nearby case dirs.

    Mirrors the classic TUI startup chooser using the shared process scan.
    """
    start = start_path.expanduser().resolve()
    seen: set[Path] = set()
    candidates: list[CaseCandidate] = []

    if is_case_dir(start):
        candidates.append(CaseCandidate(f"{start.name}  (current)", start, "current"))
        seen.add(start)

    for path, solvers, pids in _running_cases(start):
        if path in seen:
            continue
        solver_text = ",".join(solvers) or "solver"
        pid_text = ",".join(str(pid) for pid in pids[:3]) or "?"
        candidates.append(
            CaseCandidate(f"{path.name}  ● {solver_text} pid {pid_text}", path, "running"),
        )
        seen.add(path)

    scan_root = start if start.is_dir() else start.parent
    nearby: list[Path] = []
    try:
        nearby = sorted(child for child in scan_root.iterdir() if child.is_dir())
    except OSError:
        nearby = []
    for child in nearby[:200]:
        if len([c for c in candidates if c.kind == "nearby"]) >= nearby_limit:
            break
        resolved = child.resolve()
        if resolved in seen or not is_case_dir(resolved):
            continue
        candidates.append(CaseCandidate(f"{resolved.name}/", resolved, "nearby"))
        seen.add(resolved)
    return candidates


def _running_cases(start: Path) -> list[tuple[Path, tuple[str, ...], tuple[int, ...]]]:
    scope = start if start.is_dir() else start.parent
    try:
        rows = scan_proc_solver_processes(
            scope,
            None,
            tracked_pids=set(),
            include_tracked=True,
            require_case_target=False,
        )
    except (OSError, RuntimeError, ValueError):
        return []
    cases: dict[Path, tuple[set[str], set[int]]] = {}
    for row in rows:
        raw_case = str(row.get("case") or "").strip()
        if not raw_case:
            continue
        try:
            path = Path(raw_case).expanduser().resolve()
        except OSError:
            continue
        if not is_case_dir(path):
            continue
        solvers, pids = cases.setdefault(path, (set(), set()))
        solver = str(row.get("solver") or "").strip()
        if solver and solver != "unknown":
            solvers.add(solver)
        pid = row.get("pid")
        if isinstance(pid, int) and pid > 0:
            pids.add(pid)
    return [
        (path, tuple(sorted(solvers)), tuple(sorted(pids)))
        for path, (solvers, pids) in sorted(cases.items())
    ]


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
