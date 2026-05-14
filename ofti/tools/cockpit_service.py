from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.case_fingerprint import case_fingerprint
from ofti.core.plot import block_bar, sparkline
from ofti.tools import knife_service, plot_service
from ofti.tools.mesh_radar_service import mesh_radar_payload
from ofti.tools.resource_watch_service import resource_watch_payload

_DEFAULT_TAIL_BYTES = 256 * 1024


def cockpit_payload(case_path: Path, *, tail_bytes: int = _DEFAULT_TAIL_BYTES) -> dict[str, Any]:
    return {
        "case": str(case_path),
        "case_dna": case_dna_payload(case_path, tail_bytes=tail_bytes),
        "scopes": mission_scope_payload(case_path),
        "mesh_radar": mesh_radar_payload(case_path),
        "resource_watch": resource_watch_payload(case_path),
    }


def case_dna_payload(case_path: Path, *, tail_bytes: int = _DEFAULT_TAIL_BYTES) -> dict[str, Any]:
    preflight = knife_service.preflight_payload(case_path)
    status = knife_service.status_payload(case_path, lightweight=True, tail_bytes=tail_bytes)
    metrics = _safe_metrics_payload(case_path)
    try:
        initials = knife_service.initials_payload(case_path)
    except (OSError, RuntimeError, ValueError):
        initials = {}
    rtc = status.get("run_time_control") if isinstance(status.get("run_time_control"), dict) else {}
    failed = int(rtc.get("failed", 0)) if isinstance(rtc, dict) else 0
    residual_fields = list(metrics.get("residual_fields", []))
    risk = "low"
    if not preflight.get("ok") or status.get("solver_error"):
        risk = "high"
    elif failed or not residual_fields:
        risk = "medium"
    return {
        "case": str(case_path),
        "solver": status.get("solver_error") or status.get("solver") or preflight.get("solver"),
        "running": status.get("running"),
        "latest_time": status.get("latest_time"),
        "latest_iteration": status.get("latest_iteration"),
        "fields": initials.get("field_count"),
        "patches": initials.get("patch_count"),
        "residual_fields": residual_fields,
        "jobs_running": status.get("jobs_running"),
        "criteria_failed": failed,
        "risk": risk,
        "fingerprint": case_fingerprint(case_path),
    }


def mission_scope_payload(case_path: Path) -> dict[str, Any]:
    metrics, residuals = _safe_log_summary(case_path)
    rows: list[dict[str, object]] = []
    error = metrics.get("error")
    if error:
        return {"rows": [{"scope": "Log metrics", "value": "unavailable", "plot": error}]}

    courant = metrics.get("courant") if isinstance(metrics.get("courant"), dict) else {}
    co_max = _as_float(courant.get("max") if isinstance(courant, dict) else None)
    rows.append(
        {
            "scope": "Courant max",
            "value": co_max,
            "plot": block_bar(co_max, maximum=max(co_max or 0.0, 1.0), width=16),
        },
    )

    execution_value = metrics.get("execution_time")
    execution = execution_value if isinstance(execution_value, dict) else {}
    if isinstance(execution, dict):
        values = [
            _as_float(execution.get("delta_min")),
            _as_float(execution.get("delta_avg")),
            _as_float(execution.get("delta_max")),
        ]
        rows.append(
            {
                "scope": "Sec/iter",
                "value": execution.get("delta_avg"),
                "plot": sparkline(values, width=12),
            },
        )

    for field in list(residuals.get("fields", []))[:8]:
        field_dict = field if isinstance(field, dict) else {}
        values = [
            _as_float(field_dict.get("max")),
            _as_float(field_dict.get("last")),
            _as_float(field_dict.get("min")),
        ]
        rows.append(
            {
                "scope": f"Residual {field_dict.get('field', '?')}",
                "value": field_dict.get("last"),
                "plot": sparkline(values, width=12),
            },
        )
    return {"rows": rows}


def _safe_log_summary(case_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        summary = plot_service.log_summary_payload(case_path, residual_limit=20)
    except (AttributeError, OSError, RuntimeError, ValueError):
        return _safe_metrics_payload(case_path), _safe_residuals_payload(case_path)
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    residuals = summary.get("residuals") if isinstance(summary.get("residuals"), dict) else {}
    return metrics, residuals


def _safe_metrics_payload(case_path: Path) -> dict[str, Any]:
    try:
        return plot_service.metrics_payload(case_path)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"residual_fields": [], "error": str(exc)}


def _safe_residuals_payload(case_path: Path) -> dict[str, Any]:
    try:
        return plot_service.residuals_payload(case_path, limit=20)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"fields": [], "error": str(exc)}


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
