from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

from ofti.foamlib.logs import execution_time_deltas, parse_execution_times

SHOCK_RE = re.compile(r"(?:shock|delta\s*/?\s*d)[^0-9+\-]*(?P<value>[0-9eE.+-]+)", re.IGNORECASE)
DRAG_RE = re.compile(
    r"(?:\bcd\b|drag(?:\s+coefficient)?)\s*[:=]?\s*(?P<value>[0-9eE.+-]+)",
    re.IGNORECASE,
)
MASS_RE = re.compile(r"continuity errors.*?global\s*=\s*(?P<value>[0-9eE.+-]+)", re.IGNORECASE)


class ShockSummary(TypedDict):
    count: int
    last: float | None
    drift: float | None
    limit: float
    ok: bool


class DragSummary(TypedDict):
    count: int
    last: float | None
    band: float | None
    limit: float
    ok: bool


class MassSummary(TypedDict):
    count: int
    last_abs_global: float | None
    limit: float
    ok: bool


class ResidualSummary(TypedDict):
    fields: list[str]
    flatline_fields: list[str]
    flatline: bool


class ThermoSummary(TypedDict):
    out_of_range_count: int
    ok: bool


class ConvergencePayload(TypedDict):
    log: str
    shock: ShockSummary
    drag: DragSummary
    mass: MassSummary
    residuals: ResidualSummary
    thermo: ThermoSummary
    strict: bool
    strict_ok: bool
    ok: bool


class StabilityPayload(TypedDict):
    log: str
    pattern: str
    count: int
    window: int
    tolerance: float
    comparator: str
    latest: float | None
    window_delta: float | None
    status: str
    unmet_reason: str | None
    eta_seconds: float | None


class WindowedStabilityState(TypedDict):
    count: int
    latest: float | None
    window_delta: float | None
    status: str
    unmet_reason: str | None
    eta_seconds: float | None


def converge_from_text(
    log_path: Path,
    text: str,
    *,
    residuals: dict[str, list[float]],
    strict: bool = False,
    shock_drift_limit: float = 0.02,
    drag_band_limit: float = 0.02,
    mass_limit: float = 1e-4,
) -> ConvergencePayload:
    lines = text.splitlines()
    shock_values = collect_floats(lines, SHOCK_RE)
    drag_values = collect_floats(lines, DRAG_RE)
    mass_values = [abs(value) for value in collect_floats(lines, MASS_RE)]

    shock_drift = band(shock_values)
    drag_band = band(drag_values[-20:])
    mass_last = mass_values[-1] if mass_values else None
    thermo_oob = thermo_out_of_range_count(lines)
    flatline = residual_flatline(residuals)

    shock_ok = shock_drift is not None and shock_drift <= shock_drift_limit
    drag_ok = drag_band is not None and drag_band <= drag_band_limit
    mass_ok = mass_last is not None and mass_last <= mass_limit
    thermo_ok = thermo_oob == 0
    strict_ok = shock_ok and drag_ok and mass_ok

    return {
        "log": str(log_path),
        "shock": {
            "count": len(shock_values),
            "last": shock_values[-1] if shock_values else None,
            "drift": shock_drift,
            "limit": shock_drift_limit,
            "ok": shock_ok,
        },
        "drag": {
            "count": len(drag_values),
            "last": drag_values[-1] if drag_values else None,
            "band": drag_band,
            "limit": drag_band_limit,
            "ok": drag_ok,
        },
        "mass": {
            "count": len(mass_values),
            "last_abs_global": mass_last,
            "limit": mass_limit,
            "ok": mass_ok,
        },
        "residuals": {
            "fields": sorted(residuals),
            "flatline_fields": flatline,
            "flatline": bool(flatline),
        },
        "thermo": {
            "out_of_range_count": thermo_oob,
            "ok": thermo_ok,
        },
        "strict": strict,
        "strict_ok": strict_ok,
        "ok": strict_ok if strict else (shock_ok and drag_ok and mass_ok and thermo_ok),
    }


def collect_floats(lines: list[str], pattern: re.Pattern[str]) -> list[float]:
    values: list[float] = []
    for line in lines:
        match = pattern.search(line)
        if match is None:
            continue
        value = to_float(match.group("value"))
        if value is not None:
            values.append(value)
    return values


def to_float(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().strip(";")
    try:
        return float(cleaned)
    except ValueError:
        return None


def band(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values) - min(values)


def thermo_out_of_range_count(lines: list[str]) -> int:
    count = 0
    for line in lines:
        lower = line.lower()
        if "out of range" not in lower:
            continue
        if any(
            token in lower
            for token in ("thermo", "temperature", "enthalpy", "cp", "mu", "rho")
        ):
            count += 1
    return count


def residual_flatline(residuals: dict[str, list[float]]) -> list[str]:
    flat: list[str] = []
    for field, values in residuals.items():
        if len(values) < 4:
            continue
        head = max(values[:4])
        tail_window = values[-4:]
        tail_max = max(tail_window)
        tail_min = min(tail_window)
        if head <= 0:
            continue
        improved = head / max(tail_max, 1e-30)
        if improved < 2.0 or abs(tail_max - tail_min) <= max(1e-12, tail_max * 0.05):
            flat.append(field)
    return sorted(flat)


def extract_series(text: str, pattern: str) -> list[float]:
    compiled = re.compile(pattern, re.IGNORECASE)
    values: list[float] = []
    for raw in text.splitlines():
        match = compiled.search(raw)
        if match is None:
            continue
        value_text = match.groupdict().get("value")
        if value_text is None and match.groups():
            value_text = match.group(1)
        value = to_float(value_text)
        if value is not None:
            values.append(value)
    return values


def windowed_stability(
    values: list[float],
    *,
    tolerance: float,
    window: int = 8,
    startup_samples: int = 0,
    comparator: str = "le",
    sec_per_sample: float | None = None,
) -> WindowedStabilityState:
    if window <= 1:
        raise ValueError("window must be > 1")
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    state = _initial_stability_state(values, startup_samples=startup_samples, window=window)
    if state is not None:
        return state
    count = len(values)
    latest = values[-1]
    tail = values[-window:]
    delta = max(tail) - min(tail)
    passed = delta <= tolerance if comparator == "le" else delta >= tolerance
    if passed:
        return {
            "count": count,
            "latest": latest,
            "window_delta": delta,
            "status": "pass",
            "unmet_reason": None,
            "eta_seconds": 0.0,
        }
    eta = _stability_eta(
        values,
        tolerance=tolerance,
        window=window,
        comparator=comparator,
        sec_per_sample=sec_per_sample,
    )
    return {
        "count": count,
        "latest": latest,
        "window_delta": delta,
        "status": "fail",
        "unmet_reason": "window",
        "eta_seconds": eta,
    }


def stability_from_text(
    log_path: Path,
    text: str,
    *,
    pattern: str,
    tolerance: float,
    window: int,
    startup_samples: int,
    comparator: str = "le",
) -> StabilityPayload:
    values = extract_series(text, pattern)
    exec_times = parse_execution_times(text)
    deltas = execution_time_deltas(exec_times)
    sec_per_sample = (sum(deltas[-8:]) / len(deltas[-8:])) if deltas else None
    state = windowed_stability(
        values,
        tolerance=tolerance,
        window=window,
        startup_samples=startup_samples,
        comparator=comparator,
        sec_per_sample=sec_per_sample,
    )
    return {
        "log": str(log_path),
        "pattern": pattern,
        "count": int(state["count"]),
        "window": window,
        "tolerance": tolerance,
        "comparator": comparator,
        "latest": state["latest"],
        "window_delta": state["window_delta"],
        "status": state["status"],
        "unmet_reason": state["unmet_reason"],
        "eta_seconds": state["eta_seconds"],
    }


def _initial_stability_state(
    values: list[float],
    *,
    startup_samples: int,
    window: int,
) -> WindowedStabilityState | None:
    count = len(values)
    latest = values[-1] if values else None
    if count < max(1, startup_samples):
        return {
            "count": count,
            "latest": latest,
            "window_delta": None,
            "status": "fail",
            "unmet_reason": "startup",
            "eta_seconds": None,
        }
    if count < window:
        return {
            "count": count,
            "latest": latest,
            "window_delta": None,
            "status": "fail",
            "unmet_reason": "not_enough_samples",
            "eta_seconds": None,
        }
    return None


def _window_deltas(values: list[float], *, window: int) -> list[float]:
    deltas: list[float] = []
    for idx in range(window, len(values) + 1):
        tail = values[idx - window : idx]
        deltas.append(max(tail) - min(tail))
    return deltas


def _stability_eta(
    values: list[float],
    *,
    tolerance: float,
    window: int,
    comparator: str,
    sec_per_sample: float | None,
) -> float | None:
    if sec_per_sample is None or sec_per_sample <= 0 or len(values) < window + 2:
        return None
    deltas = _window_deltas(values, window=window)
    if len(deltas) < 3:
        return None
    trend_window = min(6, len(deltas) - 1)
    slope = (deltas[-1] - deltas[-(trend_window + 1)]) / trend_window
    if slope == 0:
        return None
    if (comparator == "le" and slope < 0) or (comparator == "ge" and slope > 0):
        samples_needed = (tolerance - deltas[-1]) / slope
    else:
        return None
    if samples_needed < 0:
        return None
    return samples_needed * sec_per_sample
