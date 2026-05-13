from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ofti.tools import table_render_service
from ofti.tools.alert_service import overview_alert_cards
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import plot as plot_ops
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.cli_tools import watch as watch_ops
from ofti.tools.cockpit_service import case_dna_payload, mission_scope_payload
from ofti.tools.lint_service import lint_payload
from ofti.tools.log_fold_service import fold_log_lines
from ofti.tools.mesh_radar_service import mesh_radar_payload
from ofti.tools.resource_watch_service import resource_watch_payload

_OVERVIEW_TAIL_BYTES = 256 * 1024
_COCKPIT_PANEL_MIN_WIDTH = 32


def overview_text(case_path: Path) -> str:
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
        _safe_section("Case DNA", lambda: _case_dna_lines(case_path)),
        _safe_section("Mission Scopes", lambda: _scope_lines(case_path)),
        _safe_section("Mesh Radar", lambda: _mesh_radar_lines(case_path)),
        _safe_section("Resource Watch", lambda: _resource_watch_lines(case_path)),
        _safe_section("Preflight", lambda: _preflight_lines(case_path)),
        _safe_section("Case Doctor", lambda: _doctor_lines(case_path)),
        _safe_section("Case Lint", lambda: _lint_lines(case_path)),
        _safe_section("Alert Cards", lambda: _alert_lines(case_path)),
        _safe_section("Runtime Status", lambda: _status_lines(case_path)),
        _safe_section("Live Jobs And Processes", lambda: _current_lines(case_path)),
        _safe_section("Live Cases Monitor", lambda: _live_cases_lines(case_path)),
        _safe_section("ETA", lambda: _eta_lines(case_path)),
        _safe_section("Log + Residual Split View", lambda: _log_residual_split_lines(case_path)),
        _safe_section("Folded Log", lambda: _folded_log_lines(case_path)),
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
    producers: dict[str, Callable[[], list[str]]] = {
        "Flight": lambda: _status_lines(case_path),
        "Mission scopes": lambda: _scope_lines(case_path),
        "Alerts": lambda: _alert_lines(case_path),
        "Live cases": lambda: _live_cases_lines(case_path),
        "Case lint": lambda: _lint_lines(case_path),
        "Mesh radar": lambda: _mesh_radar_lines(case_path),
        "Resource watch": lambda: _resource_watch_lines(case_path),
        "Log radar": lambda: _log_residual_split_lines(case_path),
    }
    return _safe_lines(producers.get(panel, lambda: ["unknown panel"]))


def cockpit_lines(case_path: Path, width: int = 100, selected_panel: int = 0) -> list[str]:
    """Render the default read-only captains deck as dense, bounded text panels."""
    width = max(60, width)
    inner_width = max(_COCKPIT_PANEL_MIN_WIDTH, width - 2)
    column_width = max(_COCKPIT_PANEL_MIN_WIDTH, (width - 3) // 2)
    panel_names = cockpit_panel_names()
    selected_name = panel_names[selected_panel % len(panel_names)]

    if width < 88:
        return [
            _title_line("OFTI CAPTAINS DECK", f"case={case_path.name}", width),
            _panel_selector(panel_names, selected_panel, width),
            *_panel(
                _focus_title(selected_name, panel_names, selected_panel),
                _compact_lines(
                    _selected_panel_lines(case_path, selected_name),
                    limit=14,
                ),
                inner_width,
            ),
            _title_line("Keys", "tab/l next | h prev | Enter detail | r refresh | m menu", width),
        ]

    return [
        _title_line("OFTI CAPTAINS DECK", f"case={case_path.name}", width),
        _panel_selector(panel_names, selected_panel, width),
        *_mission_strip(case_path, width),
        *_panel(
            _focus_title("Flight", panel_names, selected_panel),
            _compact_lines(_safe_lines(lambda: _status_lines(case_path)), limit=9),
            inner_width,
        ),
        *_two_column_panels(
            (
                _focus_title("Mission scopes", panel_names, selected_panel),
                _compact_lines(_safe_lines(lambda: _scope_lines(case_path)), limit=8),
            ),
            (
                _focus_title("Alerts", panel_names, selected_panel),
                _compact_lines(_safe_lines(lambda: _alert_lines(case_path)), limit=8),
            ),
            column_width,
        ),
        *_two_column_panels(
            (
                _focus_title("Live cases", panel_names, selected_panel),
                _compact_lines(_safe_lines(lambda: _live_cases_lines(case_path)), limit=8),
            ),
            (
                _focus_title("Case lint", panel_names, selected_panel),
                _compact_lines(_safe_lines(lambda: _lint_lines(case_path)), limit=8),
            ),
            column_width,
        ),
        *_two_column_panels(
            (
                _focus_title("Mesh radar", panel_names, selected_panel),
                _compact_lines(_safe_lines(lambda: _mesh_radar_lines(case_path)), limit=8),
            ),
            (
                _focus_title("Resource watch", panel_names, selected_panel),
                _compact_lines(_safe_lines(lambda: _resource_watch_lines(case_path)), limit=8),
            ),
            column_width,
        ),
        *_panel(
            _focus_title("Log radar", panel_names, selected_panel),
            _compact_lines(_safe_lines(lambda: _log_residual_split_lines(case_path)), limit=12),
            inner_width,
        ),
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


def _selected_panel_lines(case_path: Path, panel: str) -> list[str]:
    return cockpit_panel_detail_lines(case_path, panel)


def _mission_strip(case_path: Path, width: int) -> list[str]:
    lines = _safe_lines(lambda: _status_lines(case_path))
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


def _two_column_panels(
    left: tuple[str, list[str]],
    right: tuple[str, list[str]],
    width: int,
) -> list[str]:
    left_panel = _panel(left[0], left[1], width)
    right_panel = _panel(right[0], right[1], width)
    height = max(len(left_panel), len(right_panel))
    left_panel.extend(" " * (width + 2) for _ in range(height - len(left_panel)))
    right_panel.extend(" " * (width + 2) for _ in range(height - len(right_panel)))
    return [
        f"{left_line} {right_line}"
        for left_line, right_line in zip(left_panel, right_panel, strict=True)
    ]


def _compact_lines(lines: list[str], *, limit: int) -> list[str]:
    compact = [line for line in lines if line.strip()]
    if len(compact) <= limit:
        return compact
    return [*compact[: max(0, limit - 1)], f"... {len(compact) - limit + 1} more"]


def _clip(text: object, width: int) -> str:
    value = str(text).replace("\t", " ")
    return value[: max(1, width)]


def _preflight_lines(case_path: Path) -> list[str]:
    payload = knife_ops.preflight_payload(case_path)
    return table_render_service.preflight_table_lines(payload)


def _case_dna_lines(case_path: Path) -> list[str]:
    return table_render_service.case_dna_table_lines(
        case_dna_payload(case_path, tail_bytes=_OVERVIEW_TAIL_BYTES),
    )


def _scope_lines(case_path: Path) -> list[str]:
    return table_render_service.scope_table_lines(mission_scope_payload(case_path))


def _mesh_radar_lines(case_path: Path) -> list[str]:
    return table_render_service.mesh_radar_table_lines(mesh_radar_payload(case_path))


def _resource_watch_lines(case_path: Path) -> list[str]:
    return table_render_service.resource_watch_table_lines(resource_watch_payload(case_path))


def _doctor_lines(case_path: Path) -> list[str]:
    payload = knife_ops.doctor_payload(case_path)
    return table_render_service.doctor_table_lines(payload)


def _lint_lines(case_path: Path) -> list[str]:
    return table_render_service.lint_table_lines(lint_payload(case_path))


def _status_lines(case_path: Path) -> list[str]:
    payload = knife_ops.status_payload(
        case_path,
        lightweight=True,
        tail_bytes=_OVERVIEW_TAIL_BYTES,
    )
    return table_render_service.status_table_lines(payload)


def _current_lines(case_path: Path) -> list[str]:
    try:
        payload = knife_ops.current_payload(case_path, live=True)
    except TypeError:
        payload = knife_ops.current_payload(case_path)
    return table_render_service.current_table_lines(payload)


def _alert_lines(case_path: Path) -> list[str]:
    preflight = knife_ops.preflight_payload(case_path)
    doctor = knife_ops.doctor_payload(case_path)
    status = knife_ops.status_payload(
        case_path,
        lightweight=True,
        tail_bytes=_OVERVIEW_TAIL_BYTES,
    )
    try:
        current = knife_ops.current_payload(case_path, live=True)
    except TypeError:
        current = knife_ops.current_payload(case_path)
    metrics = plot_ops.metrics_payload(case_path)
    residuals = plot_ops.residuals_payload(case_path, limit=20)
    cards = overview_alert_cards(
        preflight=preflight,
        doctor=doctor,
        status=status,
        current=current,
        metrics=metrics,
        residuals=residuals,
    )
    return table_render_service.alert_cards_table_lines(cards)


def _live_cases_lines(case_path: Path) -> list[str]:
    payload = run_ops.status_set_payload(
        set_dir=case_path.parent,
        explicit_cases=[],
        case_glob="*",
        summary_csv=None,
        lightweight=True,
        tail_bytes=_OVERVIEW_TAIL_BYTES,
    )
    return table_render_service.live_cases_table_lines(payload)


def _eta_lines(case_path: Path) -> list[str]:
    payload = knife_ops.eta_payload(
        case_path,
        mode="auto",
        lightweight=True,
        tail_bytes=_OVERVIEW_TAIL_BYTES,
    )
    return table_render_service.eta_table_lines(payload)


def _log_metrics_lines(case_path: Path) -> list[str]:
    payload = plot_ops.metrics_payload(case_path)
    return table_render_service.metrics_table_lines(payload)


def _residual_lines(case_path: Path) -> list[str]:
    payload = plot_ops.residuals_payload(case_path, limit=20)
    fields = list(payload.get("fields", []))
    lines = table_render_service.residual_payload_table_lines(payload)
    if not fields:
        lines.append("No residuals found.")
        return lines
    return lines


def _log_residual_split_lines(case_path: Path) -> list[str]:
    metrics = _log_metrics_lines(case_path)
    residuals = _residual_lines(case_path)
    return _split_columns("Log metrics", metrics, "Residuals", residuals)


def _folded_log_lines(case_path: Path) -> list[str]:
    payload = watch_ops.log_tail_payload(case_path, lines=80)
    folded = fold_log_lines(list(payload.get("lines", [])))
    return table_render_service.folded_log_table_lines(
        {"log": payload.get("log"), "rows": folded},
    )


def _split_columns(
    left_title: str,
    left_lines: list[str],
    right_title: str,
    right_lines: list[str],
) -> list[str]:
    left = [left_title, "-" * len(left_title), *left_lines]
    right = [right_title, "-" * len(right_title), *right_lines]
    width = min(max((len(line) for line in left), default=0), 72)
    count = max(len(left), len(right))
    rows: list[str] = []
    for index in range(count):
        left_text = left[index] if index < len(left) else ""
        right_text = right[index] if index < len(right) else ""
        rows.append(f"{left_text[:width]:<{width}} | {right_text}")
    return rows


def _safe_section(title: str, build_lines: Callable[[], list[str]]) -> list[str]:
    try:
        lines = list(build_lines())
    except (OSError, RuntimeError, ValueError) as exc:
        lines = [f"unavailable: {exc}"]
    return _section(title, lines)


def _safe_lines(build_lines: Callable[[], list[str]]) -> list[str]:
    try:
        return list(build_lines())
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        return [f"unavailable: {exc}"]


def _section(title: str, lines: list[str]) -> list[str]:
    return [title, "-" * len(title), *lines, ""]
