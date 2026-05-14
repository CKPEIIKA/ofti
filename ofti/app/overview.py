from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ofti.tools.captains_deck_service import (
    OVERVIEW_TAIL_BYTES,
    CaptainsDeckData,
    CaptainsDeckDeps,
    case_dna_payload,
    mission_scope_payload,
)
from ofti.tools.captains_deck_service import (
    safe_lines as deck_safe_lines,
)
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import plot as plot_ops  # noqa: F401
from ofti.tools.cli_tools import run as run_ops  # noqa: F401
from ofti.tools.cli_tools import watch as watch_ops  # noqa: F401
from ofti.tools.lint_service import lint_payload
from ofti.tools.mesh_radar_service import mesh_radar_payload
from ofti.tools.resource_watch_service import resource_watch_payload

_OVERVIEW_TAIL_BYTES = OVERVIEW_TAIL_BYTES
_COCKPIT_PANEL_MIN_WIDTH = 32


def _deck_data(case_path: Path) -> CaptainsDeckData:
    return CaptainsDeckData(
        case_path,
        deps=CaptainsDeckDeps(
            case_dna_payload=case_dna_payload,
            mission_scope_payload=mission_scope_payload,
            lint_payload=lint_payload,
            mesh_radar_payload=mesh_radar_payload,
            resource_watch_payload=resource_watch_payload,
        ),
    )


def overview_text(case_path: Path) -> str:
    data = _deck_data(case_path)
    sections: list[list[str]] = [
        _section(
            "Overview",
            [
                f"case={case_path}",
                (
                    "Read-only CLI coverage: knife preflight, knife doctor, "
                    "knife status/current/criteria/eta/report, plot metrics/residuals."
                ),
            ],
        ),
        _safe_section("Case DNA", data.case_dna_lines),
        _safe_section("Mission Scopes", data.scope_lines),
        _safe_section("Mesh Radar", data.mesh_radar_lines),
        _safe_section("Resource Watch", data.resource_watch_lines),
        _safe_section("Preflight", data.preflight_lines),
        _safe_section("Case Doctor", data.doctor_lines),
        _safe_section("Case Lint", data.lint_lines),
        _safe_section("Alert Cards", data.alert_lines),
        _safe_section("Runtime Status", data.status_lines),
        _safe_section("Live Jobs And Processes", data.current_lines),
        _safe_section("Live Cases Monitor", data.live_cases_lines),
        _safe_section("ETA", data.eta_lines),
        _safe_section("Log + Residual Split View", data.log_residual_split_lines),
        _safe_section("Folded Log", data.folded_log_lines),
    ]
    return "\n".join(line for section in sections for line in section).rstrip()


def cockpit_panel_names() -> list[str]:
    return [
        "Flight",
        "Mission scopes",
        "Alerts",
        "Live cases",
        "Case lint",
        "Mesh radar",
        "Resource watch",
        "Log radar",
    ]


def cockpit_panel_detail_lines(case_path: Path, panel: str) -> list[str]:
    return _deck_data(case_path).panel_lines(panel)


def cockpit_lines(case_path: Path, width: int = 100, selected_panel: int = 0) -> list[str]:
    """Render the default read-only captains deck as dense, bounded text panels."""
    width = max(60, width)
    inner_width = max(_COCKPIT_PANEL_MIN_WIDTH, width - 2)
    panel_names = cockpit_panel_names()
    selected_name = panel_names[selected_panel % len(panel_names)]
    data = _deck_data(case_path)
    selected_lines = _compact_lines(data.panel_lines(selected_name), limit=16 if width < 88 else 20)

    if width < 88:
        return [
            _title_line("OFTI CAPTAINS DECK", f"case={case_path.name}", width),
            _panel_selector(panel_names, selected_panel, width),
            *_panel(
                _focus_title(selected_name, panel_names, selected_panel),
                selected_lines,
                inner_width,
            ),
            _title_line("Keys", "tab/l next | h prev | Enter detail | r refresh | m menu", width),
        ]

    return [
        _title_line("OFTI CAPTAINS DECK", f"case={case_path.name}", width),
        _panel_selector(panel_names, selected_panel, width),
        *_mission_strip(data, width),
        *_panel(
            _focus_title(selected_name, panel_names, selected_panel),
            selected_lines,
            inner_width,
        ),
        *_panel("Deck map", _deck_map_lines(panel_names, selected_panel), inner_width),
        _title_line(
            "Keys",
            "tab/l next | h prev | Enter detail | r refresh | m menu | q quit",
            width,
        ),
    ]


def running_header_metadata(case_path: Path, meta: dict[str, str]) -> dict[str, str]:
    try:
        payload = knife_ops.status_payload(
            case_path,
            lightweight=True,
            tail_bytes=_OVERVIEW_TAIL_BYTES,
        )
    except (OSError, ValueError):
        return meta
    if not payload.get("running") and not payload.get("jobs_running"):
        return meta

    enriched = dict(meta)
    enriched["running"] = "yes"
    enriched["jobs_running"] = str(payload.get("jobs_running", 0))
    enriched["jobs_tracked_running"] = str(payload.get("jobs_tracked_running", 0))
    enriched["live_processes"] = str(
        len(payload.get("tracked_solver_processes", []))
        + len(payload.get("untracked_solver_processes", [])),
    )
    for source, target in (
        ("latest_iteration", "latest_iteration"),
        ("latest_delta_t", "latest_delta_t"),
        ("sec_per_iter", "sec_per_iter"),
        ("eta_seconds_to_end_time", "eta_end"),
        ("eta_seconds_to_criteria_start", "eta_criteria"),
    ):
        value = payload.get(source)
        if value is not None:
            enriched[target] = str(value)
    if payload.get("log_fresh"):
        enriched["log_fresh"] = "fresh"
    return enriched


def _title_line(left: str, right: str, width: int) -> str:
    text = f" {left} // {right} "
    return text[:width].center(width, "=")


def _panel_selector(names: list[str], selected: int, width: int) -> str:
    parts = [
        f"[{name}]" if index == selected % len(names) else name
        for index, name in enumerate(names)
    ]
    return ("Panels: " + " | ".join(parts))[:width]


def _focus_title(title: str, names: list[str], selected: int) -> str:
    return f">> {title}" if names[selected % len(names)] == title else title


def _mission_strip(data: CaptainsDeckData, width: int) -> list[str]:
    lines = _safe_lines(data.status_lines)
    values = _extract_key_values(lines)
    items = [
        ("solver", values.get("solver", "unknown")),
        ("running", values.get("running", "no")),
        ("t", values.get("latest_time", "n/a")),
        ("iter", values.get("latest_iteration", "n/a")),
        ("jobs", values.get("jobs_running", "0")),
    ]
    rendered = "  ".join(f"{key}:{value}" for key, value in items)
    return [_title_line("Flight Snapshot", rendered, width)]


def _deck_map_lines(names: list[str], selected: int) -> list[str]:
    return [
        f"{index + 1}. {_focus_title(name, names, selected)}"
        for index, name in enumerate(names)
    ]


def _extract_key_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in {"Key", "-----", "Runtime"}:
            values.setdefault(parts[0], " ".join(parts[1:]))
    return values


def _panel(title: str, lines: list[str], width: int) -> list[str]:
    width = max(_COCKPIT_PANEL_MIN_WIDTH, width)
    top = f"+- {title} " + "-" * max(0, width - len(title) - 4) + "+"
    bottom = "+" + "-" * width + "+"
    body = [f"| {_clip(line, width - 2).ljust(width - 2)} |" for line in (lines or ["(no data)"])]
    return [top, *body, bottom]


def _compact_lines(lines: list[str], *, limit: int) -> list[str]:
    compact = [line for line in lines if line.strip()]
    if len(compact) <= limit:
        return compact
    return [*compact[: max(0, limit - 1)], f"... {len(compact) - limit + 1} more"]


def _clip(text: object, width: int) -> str:
    value = str(text).replace("\t", " ")
    return value[: max(1, width)]


def _preflight_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).preflight_lines()


def _case_dna_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).case_dna_lines()


def _scope_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).scope_lines()


def _mesh_radar_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).mesh_radar_lines()


def _resource_watch_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).resource_watch_lines()


def _doctor_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).doctor_lines()


def _lint_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).lint_lines()


def _status_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).status_lines()


def _current_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).current_lines()


def _alert_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).alert_lines()


def _live_cases_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).live_cases_lines()


def _eta_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).eta_lines()


def _log_metrics_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).log_metrics_lines()


def _residual_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).residual_lines()


def _log_residual_split_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).log_residual_split_lines()


def _folded_log_lines(case_path: Path) -> list[str]:
    return _deck_data(case_path).folded_log_lines()


def _safe_section(title: str, build_lines: Callable[[], list[str]]) -> list[str]:
    try:
        lines = list(build_lines())
    except (OSError, RuntimeError, ValueError) as exc:
        lines = [f"unavailable: {exc}"]
    return _section(title, lines)


def _safe_lines(build_lines: Callable[[], list[str]]) -> list[str]:
    return deck_safe_lines(build_lines)


def _section(title: str, lines: list[str]) -> list[str]:
    return [title, "-" * len(title), *lines, ""]
