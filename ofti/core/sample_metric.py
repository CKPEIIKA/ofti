"""Scalar metrics derived from sampled tables and OpenFOAM field values."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path


@dataclass(frozen=True)
class MetricSample:
    coordinate: float
    value: float
    source: str


def read_numeric_rows(path: Path) -> list[tuple[float, ...]]:
    rows: list[tuple[float, ...]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        row = _parse_numeric_line(raw)
        if row is None:
            continue
        if not all(math.isfinite(value) for value in row):
            raise ValueError(f"nonfinite sample value in {path}:{line_number}")
        rows.append(row)
    return rows


def series_samples(
    rows: list[tuple[float, ...]],
    *,
    source: str,
    coordinate_column: int,
    value_column: int,
    scale: float = 1.0,
    offset: float = 0.0,
) -> list[MetricSample]:
    return [
        MetricSample(
            coordinate=_column(row, coordinate_column),
            value=_column(row, value_column) * scale + offset,
            source=source,
        )
        for row in rows
    ]


def threshold_crossing(
    rows: list[tuple[float, ...]],
    *,
    coordinate_column: int,
    value_column: int,
    threshold: float,
    direction: str = "any",
    pick: str = "first",
) -> float | None:
    if direction not in {"any", "rising", "falling"}:
        raise ValueError(f"unsupported crossing direction: {direction}")
    if pick not in {"first", "last"}:
        raise ValueError(f"unsupported crossing selection: {pick}")
    points = [(_column(row, coordinate_column), _column(row, value_column)) for row in rows]
    crossings = [
        crossing
        for left, right in pairwise(points)
        if (crossing := _segment_crossing(left, right, threshold, direction)) is not None
    ]
    if not crossings:
        return None
    return crossings[-1] if pick == "last" else crossings[0]


def summarize_metric(
    name: str,
    samples: list[MetricSample],
    *,
    window: int,
    max_span: float | None,
) -> dict[str, object]:
    if not samples:
        raise ValueError("metric source contains no usable samples")
    if window < 1:
        raise ValueError("--window must be at least 1")
    if max_span is not None and max_span < 0:
        raise ValueError("--max-span cannot be negative")
    ordered = sorted(samples, key=lambda sample: (sample.coordinate, sample.source))
    recent = ordered[-window:]
    values = [sample.value for sample in recent]
    span = max(values) - min(values)
    mature = None if max_span is None else len(ordered) >= window and span <= max_span
    return {
        "name": name,
        "value": ordered[-1].value,
        "coordinate": ordered[-1].coordinate,
        "sample_count": len(ordered),
        "window": window,
        "window_count": len(recent),
        "last_n_span": span,
        "max_span": max_span,
        "mature": mature,
        "maturity_reason": _maturity_reason(len(ordered), window, span, max_span),
        "window_samples": [asdict(sample) for sample in recent],
    }


def summarize_field_values(
    rows: list[tuple[float, ...]],
    *,
    reduction: str,
    component: str,
    scale: float = 1.0,
    offset: float = 0.0,
) -> dict[str, object]:
    """Reduce scalar or component-selected field rows to one numeric metric."""
    values, selected_component = _field_scalar_values(rows, component)
    transformed = [value * scale + offset for value in values]
    finite = [value for value in transformed if math.isfinite(value)]
    statistics = _field_statistics(finite)
    return {
        "value": statistics[reduction],
        "reduction": reduction,
        "component": selected_component,
        "min": statistics["min"],
        "max": statistics["max"],
        "mean": statistics["mean"],
        "value_count": len(transformed),
        "finite_count": len(finite),
        "nonfinite_count": len(transformed) - len(finite),
        "ok": bool(finite) and len(finite) == len(transformed),
    }


def _field_scalar_values(
    rows: list[tuple[float, ...]],
    component: str,
) -> tuple[list[float], str]:
    if not rows:
        raise ValueError("field contains no values")
    component_counts = {len(row) for row in rows}
    if len(component_counts) != 1:
        raise ValueError("field rows have inconsistent component counts")
    component_count = component_counts.pop()
    if component_count == 1:
        _validate_scalar_component(component)
        return [row[0] for row in rows], "scalar"
    if component == "magnitude":
        return [math.sqrt(sum(value * value for value in row)) for row in rows], "magnitude"
    index = _component_index(component, component_count)
    return [row[index] for row in rows], str(index)


def _validate_scalar_component(component: str) -> None:
    if component not in {"magnitude", "0", "-1"}:
        raise ValueError("scalar fields only support component 0")


def _component_index(component: str, component_count: int) -> int:
    try:
        index = int(component)
    except ValueError as exc:
        raise ValueError("--component must be 'magnitude' or an integer index") from exc
    resolved = index if index >= 0 else component_count + index
    if resolved < 0 or resolved >= component_count:
        raise ValueError(f"component {component} is unavailable for {component_count}-component values")
    return resolved


def _field_statistics(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def _parse_numeric_line(raw: str) -> tuple[float, ...] | None:
    text = raw.split("//", 1)[0].split("#", 1)[0].strip()
    if not text:
        return None
    tokens = text.translate(str.maketrans({"(": " ", ")": " ", ";": " ", ",": " "})).split()
    try:
        return tuple(float(token) for token in tokens)
    except ValueError:
        return None


def _column(row: tuple[float, ...], index: int) -> float:
    resolved = index if index >= 0 else len(row) + index
    if resolved < 0 or resolved >= len(row):
        raise ValueError(f"column {index} is unavailable in a {len(row)}-column sample row")
    return row[resolved]


def _segment_crossing(
    left: tuple[float, float],
    right: tuple[float, float],
    threshold: float,
    direction: str,
) -> float | None:
    x0, y0 = left
    x1, y1 = right
    delta0 = y0 - threshold
    delta1 = y1 - threshold
    if not _direction_matches(y0, y1, direction):
        return None
    if delta0 == 0:
        return x0
    if delta1 == 0:
        return x1
    if delta0 * delta1 > 0:
        return None
    fraction = (threshold - y0) / (y1 - y0)
    return x0 + fraction * (x1 - x0)


def _direction_matches(left: float, right: float, direction: str) -> bool:
    if direction == "rising":
        return right > left
    if direction == "falling":
        return right < left
    return True


def _maturity_reason(count: int, window: int, span: float, max_span: float | None) -> str:
    if max_span is None:
        return "not evaluated; set --max-span"
    if count < window:
        return f"not enough samples ({count}/{window})"
    if span > max_span:
        return f"last-{window} span exceeds limit"
    return f"last-{window} span is within limit"
