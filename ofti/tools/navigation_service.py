from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RootNavItem:
    label: str
    detail: str
    hint: str
    mode: str
    focus: str
    safety: str
    actions: tuple[str, ...]


ROOT_NAV_ITEMS: tuple[RootNavItem, ...] = (
    RootNavItem(
        "Captains Deck",
        "Mission-control captains deck: live cases, alerts, scopes, lint, logs.",
        "Enter opens the heavier read-only captains deck on demand.",
        "LIVE READ",
        "running cases, risk cards, scopes",
        "safe: read-only",
        ("enter: open deck", "o: full report", "r: refresh inside"),
    ),
    RootNavItem(
        "Prepare",
        "Case identity, templates, preflight, environment, and dictionary checks.",
        "Use before mesh/solve when setup completeness is the question.",
        "SETUP",
        "case identity, templates, env",
        "safe: mostly read/check",
        ("preflight", "env", "dict checks"),
    ),
    RootNavItem(
        "Mesh",
        "Mesh generation, quality tools, decomposition, and mesh radar.",
        "Use when geometry or mesh quality is active.",
        "BUILD",
        "blockMesh, checkMesh, decompose",
        "mixed: tools can write mesh",
        ("mesh radar", "checkMesh", "parallel prep"),
    ),
    RootNavItem(
        "Physics",
        "Fields, materials, turbulence, initials, and boundary matrix.",
        "Best place for physical setup and BC checks.",
        "MODEL",
        "fields, BC matrix, materials",
        "write path: dictionaries",
        ("initials", "boundary matrix", "validate"),
    ),
    RootNavItem(
        "Numerics",
        "Schemes, solution controls, relaxation, tolerances, and dictionary checks.",
        "Enter opens the shared read-only Numerics deck; edits still use config tools.",
        "SOLVER",
        "fvSchemes, fvSolution, controlDict",
        "write path: dictionaries",
        ("numerics deck", "criteria", "diff"),
    ),
    RootNavItem(
        "Launch",
        "Pipeline and solver launch actions, including serial and parallel runs.",
        "Use for go/no-go execution paths.",
        "GO/NO-GO",
        "checklist, serial, parallel",
        "active: starts processes",
        ("launch checklist", "dry run", "parallel"),
    ),
    RootNavItem(
        "Flight",
        "Live jobs, runtime criteria, ETA, reports, stop/pause/resume, and adoption.",
        "Use while the solver is running.",
        "OPERATE",
        "jobs, runtime control, ETA",
        "active: process signals",
        ("safe stop", "pause/resume", "adopt"),
    ),
    RootNavItem(
        "Analyze",
        "Logs, residuals, probes, yPlus, sampling, ParaView helpers.",
        "Read finished or running results without editing setup.",
        "INSPECT",
        "logs, residuals, probes, yPlus",
        "safe: read-only by default",
        ("log radar", "residuals", "report"),
    ),
    RootNavItem(
        "Case Ops",
        "Cleanup, generated files, logs, time directories, and housekeeping.",
        "Destructive actions stay behind confirmations.",
        "HOUSEKEEP",
        "clean, archive, snapshots",
        "destructive: confirmed",
        ("clean", "snapshot", "archive"),
    ),
)


def root_nav_labels() -> list[str]:
    return [item.label for item in ROOT_NAV_ITEMS]


def root_nav_item(label: str) -> RootNavItem:
    for item in ROOT_NAV_ITEMS:
        if item.label == label:
            return item
    return RootNavItem(
        label,
        "Open this OFTI area.",
        "Enter opens the selected screen.",
        "AREA",
        "selected OFTI tools",
        "unknown",
        ("enter: open",),
    )
