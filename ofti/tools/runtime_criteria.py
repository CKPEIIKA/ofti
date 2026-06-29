"""Criterion evaluation and ETA math (extracted from runtime_control_service).

Self-contained leaf helpers (no dependency back on runtime_control_service):
criterion observations/needles, comparator/match, unmet-reason, ETA series and
seconds, plus small log-scan utilities.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from ofti.foamlib.logs import execution_time_deltas

ITER_RE = re.compile(r"\b(?:iteration|iter)\s*[=:]\s*(?P<value>\d+)", re.IGNORECASE)
FLOAT_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")

_GENERIC_CRITERION_TOKENS = {
    "functions",
    "function",
    "conditions",
    "condition",
    "runtimecontrol",
    "control",
    "criteria",
    "criterion",
}


def to_float(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().strip(";")
    try:
        return float(cleaned)
    except ValueError:
        return None


def criterion_observations(
    key: str,
    log_text: str,
    *,
    log_lines: list[str] | None = None,
) -> list[float]:
    needles = criterion_needles(key)
    if not needles:
        return []
    values: list[float] = []
    lines = log_lines if log_lines is not None else log_text.splitlines()
    for raw in lines:
        value = _criterion_observation_line(raw, needles)
        if value is not None:
            values.append(value)
    return values


def _criterion_observation_line(raw: str, needles: list[str]) -> float | None:
    line = raw.strip()
    if not line:
        return None
    lower = line.lower()
    for needle in needles:
        value = _criterion_value_for_needle(line, lower, needle)
        if value is not None:
            return value
    return None


def _criterion_value_for_needle(line: str, lower: str, needle: str) -> float | None:
    at = lower.find(needle)
    if at < 0:
        return None
    value = float_after_index(line, at)
    if value is None:
        value = to_float(first_float(line))
    return value


def criterion_needles(key: str) -> list[str]:
    full = key.strip().lower()
    if not full:
        return []
    needles = [full]
    compact: list[str] = []
    for token in re.split(r"[./:\-]+", full):
        cleaned = _criterion_token(token)
        if not cleaned:
            continue
        compact.append(cleaned)
        if cleaned not in needles:
            needles.append(cleaned)
    _append_joined_needles(needles, compact)
    # Longest needles first avoid generic token capturing unrelated numbers.
    needles.sort(key=len, reverse=True)
    return needles


def _criterion_token(token: str) -> str:
    cleaned = "".join(ch for ch in token if ch.isalnum() or ch in {"_", "+"}).strip("_")
    if len(cleaned) < 3 or cleaned in _GENERIC_CRITERION_TOKENS:
        return ""
    return cleaned


def _append_joined_needles(needles: list[str], compact: list[str]) -> None:
    for idx in range(1, len(compact)):
        joined = f"{compact[idx - 1]} {compact[idx]}"
        if joined not in needles:
            needles.append(joined)


def float_after_index(text: str, index: int) -> float | None:
    if index < 0 or index >= len(text):
        return None
    return to_float(first_float(text[index:]))


def first_float(text: str) -> str | None:
    match = FLOAT_RE.search(text)
    if match is None:
        return None
    return match.group(0)


def rolling_band(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values) - min(values)


def criterion_uses_delta(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("delta", "band", "drift"))


def criterion_comparator(key: str) -> str:
    lowered = key.lower()
    if "min" in lowered and "max" not in lowered:
        return "ge"
    return "le"


def criterion_matches(value: float, tolerance: float, comparator: str) -> bool:
    if comparator == "ge":
        return value >= tolerance
    return value <= tolerance


def criterion_unmet_reason(
    *,
    status: str,
    evidence: str | None,
    criteria_start: float | None,
    latest_time: float | None,
    samples: int,
    minimum_samples: int = 4,
) -> str | None:
    if status == "pass":
        return None
    reason = reason_from_evidence(evidence)
    if reason is not None:
        return reason
    if criteria_start is not None and latest_time is not None and latest_time < criteria_start:
        return "startup"
    if samples < minimum_samples:
        return "not_enough_samples"
    return "window"


def criterion_eta_seconds(
    values: list[float],
    *,
    tolerance: float | None,
    comparator: str,
    execution_times: list[float],
    use_delta: bool,
    status: str,
) -> float | None:
    if status == "pass":
        return 0.0
    if tolerance is None:
        return None
    series = criterion_eta_series(values, use_delta=use_delta)
    if len(series) < 3:
        return None
    sec_per_sample = average_step_seconds(execution_times)
    if sec_per_sample is None:
        return None
    window = min(6, len(series) - 1)
    start = series[-(window + 1)]
    end = series[-1]
    slope_per_sample = (end - start) / window
    samples_needed = criterion_eta_samples_needed(
        end,
        tolerance=tolerance,
        comparator=comparator,
        slope=slope_per_sample,
    )
    if samples_needed < 0:
        return None
    return samples_needed * sec_per_sample


def reason_from_evidence(evidence: str | None) -> str | None:
    if not evidence:
        return None
    lower = evidence.lower()
    if "start" in lower or "startup" in lower:
        return "startup"
    if "not enough" in lower or "insufficient" in lower:
        return "not_enough_samples"
    if "not met" in lower:
        return "window"
    if "window" in lower:
        return "window"
    return None


def criterion_eta_series(values: list[float], *, use_delta: bool) -> list[float]:
    if not use_delta:
        return values
    bands: list[float] = []
    for idx in range(4, len(values) + 1):
        value = rolling_band(values[max(0, idx - 6) : idx])
        if value is not None:
            bands.append(value)
    return bands


def criterion_eta_samples_needed(
    current: float,
    *,
    tolerance: float,
    comparator: str,
    slope: float,
) -> float:
    if slope == 0:
        return -1.0
    if comparator == "le":
        if current <= tolerance:
            return 0.0
        if slope >= 0:
            return -1.0
    else:
        if current >= tolerance:
            return 0.0
        if slope <= 0:
            return -1.0
    return (tolerance - current) / slope


def average_step_seconds(execution_times: list[float]) -> float | None:
    deltas = execution_time_deltas(execution_times)
    if not deltas:
        return None
    window = deltas[-8:]
    average = sum(window) / len(window)
    if average <= 0:
        return None
    return average


def eta_seconds(
    latest_time_value: float | None,
    target_time: float | None,
    times: list[float],
    execution_times: list[float],
) -> float | None:
    if latest_time_value is None or target_time is None:
        return None
    if target_time <= latest_time_value:
        return 0.0
    if len(times) < 2 or len(execution_times) < 2:
        return None
    window = min(len(times), len(execution_times), 8)
    time_delta = times[-1] - times[-window]
    exec_delta = execution_times[-1] - execution_times[-window]
    if time_delta <= 0 or exec_delta <= 0:
        return None
    speed = time_delta / exec_delta
    if speed <= 0:
        return None
    return (target_time - latest_time_value) / speed


def is_log_fresh(log_path: Path | None, freshness_seconds: float = 90.0) -> bool:
    if log_path is None:
        return False
    try:
        mtime = log_path.stat().st_mtime
    except OSError:
        return False
    return (time.time() - mtime) <= freshness_seconds


def latest_iteration(text: str, fallback: int) -> int | None:
    if fallback > 0:
        return fallback
    match_values = [int(match.group("value")) for match in ITER_RE.finditer(text)]
    if match_values:
        return match_values[-1]
    return None


def first_match(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return match.group("value").strip()
