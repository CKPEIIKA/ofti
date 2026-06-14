from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ofti.core.field_io import (
    FieldData,
    flat_values,
    read_field_values,
    resolve_field_names,
    resolve_time_dir,
)


def compare_fields_payload(
    left_case: Path,
    right_case: Path,
    *,
    time_name: str = "latest",
    reference_time: str | None = None,
    candidate_time: str | None = None,
    fields: list[str] | None = None,
    preset: str | None = None,
    patch: str | None = None,
    abs_tol: float = 1e-300,
    rel_tol: float = 1e-12,
) -> dict[str, Any]:
    left_time = resolve_time_dir(left_case, reference_time or time_name)
    right_time = resolve_time_dir(right_case, candidate_time or time_name)
    names = resolve_field_names(left_time, fields, preset=preset)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for name in names:
        try:
            left = read_field_values(left_time / name, patch=patch)
            right = read_field_values(right_time / name, patch=patch)
            row = compare_field_data(left, right, abs_tol=abs_tol, rel_tol=rel_tol)
        except (OSError, ValueError) as exc:
            row = {"field": name, "ok": False, "error": str(exc)}
            errors.append(f"{name}: {exc}")
        rows.append(row)
    return {
        "left_case": str(left_case),
        "right_case": str(right_case),
        "time": left_time.name,
        "reference_time": left_time.name,
        "right_time": right_time.name,
        "candidate_time": right_time.name,
        "preset": preset,
        "patch": patch,
        "fields_requested": names,
        "field_count": len(rows),
        "ok": not errors,
        "same": not errors and all(float(row.get("max_abs", 0.0) or 0.0) == 0.0 for row in rows),
        "errors": errors,
        "fields": rows,
    }


def compare_field_data(
    left: FieldData,
    right: FieldData,
    *,
    abs_tol: float,
    rel_tol: float,
) -> dict[str, Any]:
    left_values, right_values = align_values(left, right)
    max_abs = 0.0
    rel_linf = 0.0
    rel_l2_num = 0.0
    rel_l2_den = 0.0
    rel_linf_significant = 0.0
    nonfinite = 0
    compared = 0
    left_flat: list[float] = []
    right_flat: list[float] = []
    ratios: list[float] = []
    ref_abs_max = max(
        (abs(value) for value in flat_values(left_values) if math.isfinite(value)),
        default=0.0,
    )
    significant_floor = max(abs_tol, rel_tol * ref_abs_max)
    for left_row, right_row in zip(left_values, right_values, strict=True):
        if len(left_row) != len(right_row):
            raise ValueError(
                f"component mismatch for {left.name}: {len(left_row)} vs {len(right_row)}",
            )
        for left_value, right_value in zip(left_row, right_row, strict=True):
            compared += 1
            left_flat.append(left_value)
            right_flat.append(right_value)
            if not (math.isfinite(left_value) and math.isfinite(right_value)):
                nonfinite += 1
                continue
            diff = abs(left_value - right_value)
            denom = max(abs(left_value), abs(right_value), 1e-300)
            max_abs = max(max_abs, diff)
            rel = diff / denom
            rel_linf = max(rel_linf, rel)
            rel_l2_num += diff * diff
            rel_l2_den += left_value * left_value
            if abs(left_value) > significant_floor:
                rel_linf_significant = max(rel_linf_significant, rel)
            if abs(left_value) > 1e-300:
                ratios.append(right_value / left_value)
    return {
        "field": left.name,
        "ok": True,
        "kind": left.kind if left.kind == right.kind else f"{left.kind}/{right.kind}",
        "left_count": left.count,
        "right_count": right.count,
        "components": left.component_count,
        "count": compared,
        "n": compared,
        "reference_min": finite_min(left_flat),
        "reference_max": finite_max(left_flat),
        "candidate_min": finite_min(right_flat),
        "candidate_max": finite_max(right_flat),
        "max_abs": max_abs,
        "abs_linf": max_abs,
        "max_rel": rel_linf,
        "rel_linf": rel_linf,
        "rel_l2": math.sqrt(rel_l2_num / rel_l2_den) if rel_l2_den > 0 else 0.0,
        "rel_linf_significant": rel_linf_significant,
        "ratio_min": percentile(ratios, 0.0),
        "ratio_p05": percentile(ratios, 0.05),
        "ratio_median": percentile(ratios, 0.5),
        "ratio_p95": percentile(ratios, 0.95),
        "ratio_max": percentile(ratios, 1.0),
        "nonfinite_pairs": nonfinite,
    }


def align_values(
    left: FieldData,
    right: FieldData,
) -> tuple[list[tuple[float, ...]], list[tuple[float, ...]]]:
    if left.count == right.count:
        return left.values, right.values
    if left.uniform and left.count == 1:
        return [left.values[0]] * right.count, right.values
    if right.uniform and right.count == 1:
        return left.values, [right.values[0]] * left.count
    raise ValueError(f"field count mismatch for {left.name}: {left.count} vs {right.count}")


def finite_min(values: list[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value)]
    return min(finite) if finite else None


def finite_max(values: list[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value)]
    return max(finite) if finite else None


def percentile(values: list[float], q: float) -> float | None:
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return None
    index = round((len(finite) - 1) * q)
    return finite[index]
