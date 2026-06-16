"""Criteria, ETA, and convergence/stability payload helpers.

Extracted from knife_service. Pure analysis over criteria rows, ETA selection,
and convergence/stability log reads; no process or job-registry coupling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.foamlib.logs import parse_residuals, read_log_text
from ofti.tools import case_source_service, convergence_service


def criteria_rows_from_rtc(rtc: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": row.get("key"),
            "value": row.get("live_value"),
            "target": row.get("value"),
            "tol": row.get("tolerance"),
            "status": row.get("status"),
            "met": row.get("status") == "pass",
            "unmet": row.get("unmet_reason"),
            "reason": criteria_unknown_reason(row),
            "window": {
                "samples": row.get("samples"),
                "delta": row.get("live_delta"),
            },
            "source": criterion_source(str(row.get("key", ""))),
        }
        for row in rtc.get("criteria", [])
    ]


def criteria_unknown_reason(row: dict[str, Any]) -> str | None:
    status = str(row.get("status") or "unknown")
    if status == "pass":
        return None
    unmet = row.get("unmet_reason")
    if row.get("unmet_reason") == "not_enough_samples":
        return f"not enough samples: {row.get('samples') or 0} observed"
    if unmet == "startup":
        return "waiting for criteria start time"
    if unmet == "condition_not_met":
        return "runTimeControl reports conditions not met"
    if row.get("live_value") is None and row.get("live_delta") is None:
        return "no matching runtime samples in log"
    return "trend unavailable from current samples" if row.get("eta_seconds") is None else unmet


def converge_payload(
    source: Path,
    *,
    strict: bool = False,
    shock_drift_limit: float = 0.02,
    drag_band_limit: float = 0.02,
    mass_limit: float = 1e-4,
) -> convergence_service.ConvergencePayload:
    log_path = case_source_service.resolve_log_source(source)
    text = read_log_text(log_path)
    residuals = parse_residuals(text)
    return convergence_service.converge_from_text(
        log_path,
        text,
        residuals=residuals,
        strict=strict,
        shock_drift_limit=shock_drift_limit,
        drag_band_limit=drag_band_limit,
        mass_limit=mass_limit,
    )


def stability_payload(
    source: Path,
    *,
    pattern: str,
    tolerance: float,
    window: int,
    startup_samples: int = 0,
    comparator: str = "le",
) -> convergence_service.StabilityPayload:
    log_path = case_source_service.resolve_log_source(source)
    text = read_log_text(log_path)
    return convergence_service.stability_from_text(
        log_path,
        text,
        pattern=pattern,
        tolerance=tolerance,
        window=window,
        startup_samples=startup_samples,
        comparator=comparator,
    )


def criterion_source(key: str) -> str:
    if key.startswith("functions."):
        return "runTimeControl"
    return "controlDict"


def criteria_satisfaction_eta(criteria: list[dict[str, Any]]) -> float | None:
    if not criteria:
        return None
    pending: list[dict[str, Any]] = [row for row in criteria if str(row.get("status")) != "pass"]
    if not pending:
        return 0.0
    eta_values: list[float] = []
    for row in pending:
        value = row.get("eta_seconds")
        if isinstance(value, (int, float)):
            eta_values.append(float(value))
    if not eta_values or len(eta_values) < len(pending):
        return None
    return max(eta_values)


def criteria_eta_details(
    criteria: list[dict[str, Any]],
    *,
    eta_to_criteria_start: float | None,
    eta_to_end_time: float | None,
) -> dict[str, Any]:
    pending: list[dict[str, Any]] = [row for row in criteria if str(row.get("status")) != "pass"]
    if not pending:
        return {
            "eta_worst_seconds": 0.0,
            "eta_all_seconds": 0.0,
            "confidence": 1.0,
            "reason": "criteria_already_met",
            "unavailable": [],
        }
    eta_rows: list[float] = []
    unavailable: list[dict[str, str]] = []
    for row in pending:
        eta_value = row.get("eta_seconds")
        name = str(row.get("key", "criterion"))
        reason = str(row.get("unmet_reason") or "")
        if isinstance(eta_value, (int, float)):
            eta_rows.append(float(eta_value))
            continue
        unavailable.append(
            {
                "name": name,
                "reason": reason or "eta_not_available",
            },
        )
    if eta_rows and not unavailable:
        return {
            "eta_worst_seconds": max(eta_rows),
            "eta_all_seconds": max(eta_rows),
            "confidence": 0.9,
            "reason": "criteria_trend",
            "unavailable": [],
        }
    if eta_to_criteria_start is not None and eta_to_criteria_start > 0:
        return {
            "eta_worst_seconds": eta_to_criteria_start,
            "eta_all_seconds": None,
            "confidence": 0.5,
            "reason": "criteria_start_window",
            "unavailable": unavailable,
        }
    fallback_reason = unavailable[0]["reason"] if unavailable else "criteria_eta_missing"
    if eta_to_end_time is not None:
        return {
            "eta_worst_seconds": None,
            "eta_all_seconds": None,
            "confidence": 0.3,
            "reason": fallback_reason,
            "unavailable": unavailable,
        }
    return {
        "eta_worst_seconds": None,
        "eta_all_seconds": None,
        "confidence": 0.0,
        "reason": fallback_reason,
        "unavailable": unavailable,
    }


def select_eta(
    *,
    requested_mode: str,
    criteria_details: dict[str, Any],
    eta_to_end_time: float | None,
) -> dict[str, Any]:
    if requested_mode == "endtime":
        if eta_to_end_time is None:
            return {
                "eta_seconds": None,
                "mode": "unavailable",
                "reason": "end_time_eta_unavailable",
                "confidence": 0.0,
            }
        return {
            "eta_seconds": eta_to_end_time,
            "mode": "end_time",
            "reason": "end_time_trend",
            "confidence": 0.8,
        }
    eta_worst = criteria_details.get("eta_worst_seconds")
    reason = str(criteria_details.get("reason") or "")
    confidence = float(criteria_details.get("confidence") or 0.0)
    if isinstance(eta_worst, (int, float)):
        if reason == "criteria_start_window":
            return {
                "eta_seconds": float(eta_worst),
                "mode": "criteria_start",
                "reason": reason,
                "confidence": confidence,
            }
        return {
            "eta_seconds": float(eta_worst),
            "mode": "criteria",
            "reason": reason or "criteria_trend",
            "confidence": confidence,
        }
    if eta_to_end_time is not None:
        return {
            "eta_seconds": eta_to_end_time,
            "mode": "end_time",
            "reason": reason or "criteria_unavailable",
            "confidence": min(confidence, 0.4),
        }
    return {
        "eta_seconds": None,
        "mode": "unavailable",
        "reason": reason or "criteria_unavailable",
        "confidence": 0.0,
    }


def report_markdown(payload: dict[str, Any]) -> str:
    metrics = payload.get("metrics", {})
    criteria = payload.get("criteria", {})
    eta = payload.get("eta", {})
    lines = [
        f"# OFTI Report: {payload.get('case')}",
        "",
        "## Status",
        f"- solver: {payload.get('solver')}",
        f"- running: {payload.get('running')}",
        (
            f"- log: {payload.get('log', {}).get('path')} "
            f"(fresh={payload.get('log', {}).get('fresh')})"
        ),
        "",
        "## Key metrics",
        f"- latest_time: {metrics.get('latest_time')}",
        f"- latest_iteration: {metrics.get('latest_iteration')}",
        f"- latest_delta_t: {metrics.get('latest_delta_t')}",
        f"- sec_per_iter: {metrics.get('sec_per_iter')}",
        "",
        "## Criteria",
        (
            f"- count: {criteria.get('count')} (pass={criteria.get('passed')} "
            f"fail={criteria.get('failed')} unknown={criteria.get('unknown')})"
        ),
        "",
        "## ETA",
        f"- criteria_seconds: {eta.get('criteria_seconds')}",
        f"- end_time_seconds: {eta.get('end_time_seconds')}",
        f"- criteria_start_seconds: {eta.get('criteria_start_seconds')}",
    ]
    return "\n".join(lines)
