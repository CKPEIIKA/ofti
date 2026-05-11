from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ofti.tools import table_render_service
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import plot as plot_ops

_OVERVIEW_TAIL_BYTES = 256 * 1024


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
        _safe_section("Preflight", lambda: _preflight_lines(case_path)),
        _safe_section("Case Doctor", lambda: _doctor_lines(case_path)),
        _safe_section("Runtime Status", lambda: _status_lines(case_path)),
        _safe_section("Live Jobs And Processes", lambda: _current_lines(case_path)),
        _safe_section("ETA", lambda: _eta_lines(case_path)),
        _safe_section("Log + Residual Split View", lambda: _log_residual_split_lines(case_path)),
    ]
    return "\n".join(line for section in sections for line in section).rstrip()


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


def _preflight_lines(case_path: Path) -> list[str]:
    payload = knife_ops.preflight_payload(case_path)
    return table_render_service.preflight_table_lines(payload)


def _doctor_lines(case_path: Path) -> list[str]:
    payload = knife_ops.doctor_payload(case_path)
    return table_render_service.doctor_table_lines(payload)


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


def _section(title: str, lines: list[str]) -> list[str]:
    return [title, "-" * len(title), *lines, ""]
