from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.foamlib.logs import (
    execution_time_deltas,
    parse_log_metrics_and_residuals,
    parse_residuals,
    read_log_text,
)
from ofti.tools import case_source_service


def metrics_payload(source: Path) -> dict[str, Any]:
    log_path = case_source_service.resolve_log_source(source)
    text = read_log_text(log_path)
    metrics, residuals = parse_log_metrics_and_residuals(text)
    return _metrics_payload(log_path, metrics, residuals)


def log_summary_payload(
    source: Path,
    *,
    residual_fields: list[str] | None = None,
    residual_limit: int = 20,
) -> dict[str, Any]:
    """Read a log once and return both metrics and residual summaries."""
    log_path = case_source_service.resolve_log_source(source)
    text = read_log_text(log_path)
    metrics, residuals = parse_log_metrics_and_residuals(text)
    return {
        "log": str(log_path),
        "metrics": _metrics_payload(log_path, metrics, residuals),
        "residuals": _residuals_payload(
            log_path,
            residuals,
            fields=residual_fields,
            limit=residual_limit,
        ),
    }


def _metrics_payload(
    log_path: Path,
    metrics: Any,
    residuals: dict[str, list[float]],
) -> dict[str, Any]:
    deltas = execution_time_deltas(metrics.execution_times)
    return {
        "log": str(log_path),
        "times": {
            "count": len(metrics.times),
            "last": metrics.times[-1] if metrics.times else None,
        },
        "courant": {
            "count": len(metrics.courants),
            "max": max(metrics.courants) if metrics.courants else None,
        },
        "execution_time": {
            "count": len(metrics.execution_times),
            "last": metrics.execution_times[-1] if metrics.execution_times else None,
            "delta_min": min(deltas) if deltas else None,
            "delta_avg": (sum(deltas) / len(deltas)) if deltas else None,
            "delta_max": max(deltas) if deltas else None,
        },
        "residual_fields": sorted(residuals),
    }


def residuals_payload(
    source: Path,
    *,
    fields: list[str] | None = None,
    limit: int = 0,
) -> dict[str, Any]:
    log_path = case_source_service.resolve_log_source(source)
    text = read_log_text(log_path)
    residuals = parse_residuals(text)
    return _residuals_payload(log_path, residuals, fields=fields, limit=limit)


def _residuals_payload(
    log_path: Path,
    residuals: dict[str, list[float]],
    *,
    fields: list[str] | None,
    limit: int,
) -> dict[str, Any]:
    selected = set(fields or [])
    rows: list[dict[str, Any]] = []
    for field in sorted(residuals):
        if selected and field not in selected:
            continue
        values = residuals[field]
        if not values:
            continue
        rows.append(
            {
                "field": field,
                "count": len(values),
                "last": values[-1],
                "min": min(values),
                "max": max(values),
            },
        )
    if limit > 0:
        rows = rows[:limit]
    return {"log": str(log_path), "fields": rows}
