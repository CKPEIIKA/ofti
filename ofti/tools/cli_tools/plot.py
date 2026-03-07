from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.foamlib.logs import execution_time_deltas, parse_log_metrics, parse_residuals

from .common import read_text, resolve_log_source


def metrics_payload(source: Path) -> dict[str, Any]:
    log_path = resolve_log_source(source)
    text = read_text(log_path)
    metrics = parse_log_metrics(text)
    residuals = parse_residuals(text)
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
    log_path = resolve_log_source(source)
    text = read_text(log_path)
    residuals = parse_residuals(text)
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
