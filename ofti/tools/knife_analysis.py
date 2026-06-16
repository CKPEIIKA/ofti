"""Backward-compatible aliases for log/criteria/convergence analysis helpers.

These thin wrappers delegate to ``runtime_control_service`` and
``convergence_service``. They are kept so the ``ofti knife`` command facade and
its tests can reach the underscore-prefixed names from one place, without the
knife service module carrying ~165 lines of pass-through definitions.
"""

from __future__ import annotations

import re
from pathlib import Path

from ofti.tools import convergence_service, runtime_control_service


def _run_time_control_data(
    case_path: Path,
    log_text: str,
) -> runtime_control_service.RunTimeControlPayload:
    return runtime_control_service.run_time_control_data(case_path, log_text)


def _read_with_local_includes(
    path: Path,
    *,
    case_root: Path | None = None,
    _seen: set[Path] | None = None,
) -> str:
    return runtime_control_service.read_with_local_includes(
        path,
        case_root=case_root,
        seen=_seen,
    )


def _strip_include_token(value: str) -> str:
    return runtime_control_service.strip_include_token(value)


def _resolve_include_path(
    include_kind: str,
    include_raw: str,
    include_parent: Path,
    case_root: Path,
) -> Path | None:
    return runtime_control_service.resolve_include_path(
        include_kind,
        include_raw,
        include_parent,
        case_root,
    )


def _strip_comments(text: str) -> str:
    return runtime_control_service.strip_comments(text)


def _iter_blocks_recursive(text: str, prefix: str = "") -> list[tuple[str, str]]:
    return runtime_control_service.iter_blocks_recursive(text, prefix)


def _iter_named_blocks(text: str) -> list[tuple[str, str]]:
    return runtime_control_service.iter_named_blocks(text)


def _parse_block_name(text: str, start: int) -> tuple[str, int] | None:
    return runtime_control_service.parse_block_name(text, start)


def _matching_brace(text: str, start: int) -> int:
    return runtime_control_service.matching_brace(text, start)


def _first_block_body(text: str, name: str) -> str | None:
    return runtime_control_service.first_block_body(text, name)


def _dedupe_criteria(
    rows: list[runtime_control_service.CriterionRow],
) -> list[runtime_control_service.CriterionRow]:
    return runtime_control_service.dedupe_criteria(rows)


def _inline_criteria(
    clean_text: str,
    log_text: str,
) -> list[runtime_control_service.CriterionRow]:
    return runtime_control_service.inline_criteria(clean_text, log_text)


def _runtime_control_conditions(
    clean_text: str,
    log_text: str,
) -> tuple[float | None, list[runtime_control_service.CriterionRow]]:
    return runtime_control_service.runtime_control_conditions(clean_text, log_text)


def _runtime_control_block_rows(
    block_key: str,
    body: str,
    log_text: str,
) -> list[runtime_control_service.CriterionRow]:
    return runtime_control_service.runtime_control_block_rows(block_key, body, log_text)


def _criterion_status(key: str, log_text: str) -> tuple[str, str | None]:
    return runtime_control_service.criterion_status(key, log_text)


def _eta_seconds(
    latest_time_value: float | None,
    target_time: float | None,
    times: list[float],
    execution_times: list[float],
) -> float | None:
    return runtime_control_service.eta_seconds(
        latest_time_value,
        target_time,
        times,
        execution_times,
    )


def _is_log_fresh(log_path: Path | None, freshness_seconds: float = 90.0) -> bool:
    return runtime_control_service.is_log_fresh(log_path, freshness_seconds)


def _latest_iteration(text: str, fallback: int) -> int | None:
    return runtime_control_service.latest_iteration(text, fallback)


def _first_match(text: str, pattern: re.Pattern[str]) -> str | None:
    return runtime_control_service.first_match(text, pattern)


def _last_float(text: str, pattern: re.Pattern[str]) -> float | None:
    return runtime_control_service.last_float(text, pattern)


def _to_float(text: str | None) -> float | None:
    return runtime_control_service.to_float(text)


def _collect_floats(lines: list[str], pattern: re.Pattern[str]) -> list[float]:
    return convergence_service.collect_floats(lines, pattern)


def _band(values: list[float]) -> float | None:
    return convergence_service.band(values)


def _thermo_out_of_range_count(lines: list[str]) -> int:
    return convergence_service.thermo_out_of_range_count(lines)


def _residual_flatline(residuals: dict[str, list[float]]) -> list[str]:
    return convergence_service.residual_flatline(residuals)


def _extract_series(text: str, pattern: str) -> list[float]:
    return convergence_service.extract_series(text, pattern)


def _windowed_stability(
    values: list[float],
    *,
    tolerance: float,
    window: int = 8,
    startup_samples: int = 0,
    comparator: str = "le",
    sec_per_sample: float | None = None,
) -> convergence_service.WindowedStabilityState:
    return convergence_service.windowed_stability(
        values,
        tolerance=tolerance,
        window=window,
        startup_samples=startup_samples,
        comparator=comparator,
        sec_per_sample=sec_per_sample,
    )
