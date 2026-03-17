from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from ofti.foamlib.logs import (
    execution_time_deltas,
    parse_log_metrics,
    parse_log_metrics_and_residuals,
    read_log_text,
    read_log_text_filtered,
)

DELTA_T_RE = re.compile(r"\bdeltaT\s*=\s*(?P<value>[0-9eE.+-]+)", re.IGNORECASE)
ITER_RE = re.compile(r"\b(?:iteration|iter)\s*[=:]\s*(?P<value>\d+)", re.IGNORECASE)
END_TIME_RE = re.compile(r"\bendTime\s+(?P<value>[^;]+);")
START_TIME_RE = re.compile(r"\bstartTime\s+(?P<value>[^;]+);")
TIME_START_RE = re.compile(r"\btimeStart\s+(?P<value>[^;]+);")
CRITERIA_RE = re.compile(
    r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_./:-]*(?:Tolerance|Delta|Band|Target|Max|Min|Drift))\s+"
    r"(?P<value>[^;]+);",
    re.MULTILINE,
)
TYPE_RE = re.compile(r"\btype\s+(?P<value>[^;]+);")
VALUE_RE = re.compile(
    r"\b(?:value|threshold|max|min|delta|tolerance|target)\s+(?P<value>[^;]+);",
    re.IGNORECASE,
)
FIELD_RE = re.compile(r"\bfield\s+(?P<value>[^;]+);")
FIELDS_RE = re.compile(r"\bfields\s*\((?P<value>[^)]*)\)\s*;", re.IGNORECASE)
INCLUDE_RE = re.compile(
    r'^\s*#(?P<kind>include|includeEtc)\s+(?P<path>"[^"]+"|<[^>]+>|\S+)',
    re.MULTILINE,
)
COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
COMMENT_LINE_RE = re.compile(r"//.*?$", re.MULTILINE)
KEY_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_./:-]*$")
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
_CONDITIONS_NOT_MET_TOKENS = ("conditions not met", "condition not met")
_CONDITIONS_MET_TOKENS = ("conditions met", "condition met")


class CriterionRow(TypedDict, total=False):
    key: str
    value: str
    status: str
    evidence: str | None
    live_value: float | None
    live_delta: float | None
    tolerance: float | None
    eta_seconds: float | None
    unmet_reason: str | None
    samples: int


class RunTimeControlPayload(TypedDict):
    end_time: float | None
    criteria_start: float | None
    criteria: list[CriterionRow]
    passed: int
    failed: int
    unknown: int


class RuntimeControlSnapshot(TypedDict):
    log_path: str | None
    log_fresh: bool
    latest_time: float | None
    latest_iteration: int | None
    latest_delta_t: float | None
    sec_per_iter: float | None
    run_time_control: RunTimeControlPayload
    eta_to_end_time: float | None
    eta_to_criteria_start: float | None
    residual_fields: list[str]


def runtime_control_snapshot(
    case_path: Path,
    solver: str | None,
    *,
    resolve_log_source_fn: Callable[[Path], Path],
    lightweight: bool = False,
    max_log_bytes: int | None = None,
) -> RuntimeControlSnapshot:
    log_path = resolve_solver_log(case_path, solver, resolve_log_source_fn=resolve_log_source_fn)
    read_limit = max_log_bytes
    if read_limit is None and lightweight:
        read_limit = 2 * 1024 * 1024
    text = ""
    if log_path is not None:
        if lightweight or read_limit is not None:
            text = read_log_text(log_path, max_bytes=read_limit)
        else:
            text = read_log_text_filtered(
                log_path,
                terms=runtime_log_terms(case_path),
            )
    if text:
        if lightweight:
            metrics, residuals = parse_log_metrics(text), {}
        else:
            metrics, residuals = parse_log_metrics_and_residuals(text)
    else:
        metrics, residuals = parse_log_metrics(""), {}
    deltas = execution_time_deltas(metrics.execution_times)
    latest_time_value = metrics.times[-1] if metrics.times else None
    latest_delta_t = last_float(text, DELTA_T_RE)
    latest_iteration_value = latest_iteration(text, len(metrics.times))
    sec_per_iter = (sum(deltas[-8:]) / len(deltas[-8:])) if deltas else None
    run_time_control = run_time_control_data(
        case_path,
        text,
        latest_time=latest_time_value,
        execution_times=metrics.execution_times,
    )
    eta_to_end = eta_seconds(
        latest_time_value,
        run_time_control.get("end_time"),
        metrics.times,
        metrics.execution_times,
    )
    eta_to_start = eta_seconds(
        latest_time_value,
        run_time_control.get("criteria_start"),
        metrics.times,
        metrics.execution_times,
    )
    return {
        "log_path": str(log_path) if log_path is not None else None,
        "log_fresh": is_log_fresh(log_path),
        "latest_time": latest_time_value,
        "latest_iteration": latest_iteration_value,
        "latest_delta_t": latest_delta_t,
        "sec_per_iter": sec_per_iter,
        "run_time_control": run_time_control,
        "eta_to_end_time": eta_to_end,
        "eta_to_criteria_start": eta_to_start,
        "residual_fields": sorted(residuals),
    }


def resolve_solver_log(
    case_path: Path,
    solver: str | None,
    *,
    resolve_log_source_fn: Callable[[Path], Path],
) -> Path | None:
    if solver:
        candidate = case_path / f"log.{solver}"
        if candidate.is_file():
            return candidate.resolve()
    try:
        return resolve_log_source_fn(case_path)
    except ValueError:
        return None


def run_time_control_data(
    case_path: Path,
    log_text: str,
    *,
    latest_time: float | None = None,
    execution_times: list[float] | None = None,
) -> RunTimeControlPayload:
    control_dict = case_path / "system" / "controlDict"
    try:
        text = read_with_local_includes(control_dict, case_root=case_path)
    except OSError:
        return {
            "end_time": None,
            "criteria_start": None,
            "criteria": [],
            "passed": 0,
            "failed": 0,
            "unknown": 0,
        }
    clean_text = strip_comments(text)
    log_lines = log_text.splitlines()
    end_time = to_float(first_match(clean_text, END_TIME_RE))
    start_time = to_float(first_match(clean_text, START_TIME_RE))
    criteria = inline_criteria(clean_text, log_text, log_lines=log_lines)
    rtc_start_time, rtc_criteria = runtime_control_conditions(
        clean_text,
        log_text,
        log_lines=log_lines,
    )
    criteria.extend(rtc_criteria)
    if rtc_start_time is not None:
        start_time = rtc_start_time
    criteria = dedupe_criteria(criteria)
    criteria = enrich_criteria(
        criteria,
        log_text,
        log_lines=log_lines,
        criteria_start=start_time,
        latest_time=latest_time,
        execution_times=execution_times or [],
    )
    passed = sum(1 for row in criteria if row["status"] == "pass")
    failed = sum(1 for row in criteria if row["status"] == "fail")
    unknown = len(criteria) - passed - failed
    return {
        "end_time": end_time,
        "criteria_start": start_time,
        "criteria": criteria,
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
    }


def runtime_log_terms(case_path: Path) -> list[str]:
    control_dict = case_path / "system" / "controlDict"
    try:
        text = read_with_local_includes(control_dict, case_root=case_path)
    except OSError:
        return []
    clean_text = strip_comments(text)
    terms: list[str] = []
    for match in CRITERIA_RE.finditer(clean_text):
        key = match.group("key").strip()
        if key:
            terms.append(key)
    for _block_key, row in runtime_control_term_rows(clean_text):
        cond_name, cond_type, field = row
        if cond_name:
            terms.append(cond_name)
        if cond_type:
            terms.append(cond_type)
        if field:
            terms.append(field)
    terms.extend(["runTimeControl", "condition", "conditions"])
    return terms


def runtime_control_term_rows(clean_text: str) -> list[tuple[str, tuple[str, str, str]]]:
    rows: list[tuple[str, tuple[str, str, str]]] = []
    for key, body in iter_blocks_recursive(clean_text):
        block_type = first_match(body, TYPE_RE)
        if block_type is None or block_type.strip().strip('"') != "runTimeControl":
            continue
        conditions = first_block_body(body, "conditions")
        if conditions is None:
            continue
        for cond_name, cond_body in iter_named_blocks(conditions):
            cond_type = (first_match(cond_body, TYPE_RE) or "").strip().strip('"')
            field = (
                (first_match(cond_body, FIELD_RE) or first_match(cond_body, FIELDS_RE) or "")
                .strip()
                .strip('"')
            )
            rows.append((key, (cond_name.strip(), cond_type, field)))
    return rows


def read_with_local_includes(
    path: Path,
    *,
    case_root: Path | None = None,
    seen: set[Path] | None = None,
) -> str:
    visited = seen if seen is not None else set()
    target = path.resolve()
    root = case_root.resolve() if case_root is not None else target.parent
    if target in visited:
        return ""
    visited.add(target)
    text = target.read_text(encoding="utf-8", errors="ignore")
    lines: list[str] = []
    for raw in text.splitlines():
        match = INCLUDE_RE.match(raw)
        if match is None:
            lines.append(raw)
            continue
        include_kind = match.group("kind")
        include_raw = strip_include_token(match.group("path").strip())
        include_path = resolve_include_path(include_kind, include_raw, target.parent, root)
        if include_path is None:
            lines.append(raw)
            continue
        try:
            included = read_with_local_includes(
                include_path,
                case_root=root,
                seen=visited,
            )
        except OSError:
            lines.append(raw)
            continue
        lines.append(included)
    return "\n".join(lines)


def strip_include_token(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("<") and value.endswith(">")
    ):
        return value[1:-1].strip()
    return value.strip()


def resolve_include_path(
    include_kind: str,
    include_raw: str,
    include_parent: Path,
    case_root: Path,
) -> Path | None:
    if not include_raw:
        return None
    expanded = os.path.expandvars(include_raw.replace("$FOAM_CASE", str(case_root)))
    include_path = Path(expanded).expanduser()
    if include_path.is_absolute():
        return include_path
    if include_kind == "includeEtc":
        foam_etc = os.environ.get("FOAM_ETC")
        wm_project_dir = os.environ.get("WM_PROJECT_DIR")
        candidates: list[Path] = []
        if foam_etc:
            candidates.append(Path(foam_etc))
        if wm_project_dir:
            candidates.append(Path(wm_project_dir) / "etc")
        for root in candidates:
            candidate = (root / include_path).resolve()
            if candidate.exists():
                return candidate
        if candidates:
            return (candidates[0] / include_path).resolve()
    return (include_parent / include_path).resolve()


def strip_comments(text: str) -> str:
    text = COMMENT_BLOCK_RE.sub("", text)
    return COMMENT_LINE_RE.sub("", text)


def iter_blocks_recursive(text: str, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for name, body in iter_named_blocks(text):
        key = f"{prefix}.{name}" if prefix else name
        rows.append((key, body))
        rows.extend(iter_blocks_recursive(body, key))
    return rows


def iter_named_blocks(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    idx = 0
    length = len(text)
    while idx < length:
        parsed = parse_block_name(text, idx)
        if parsed is None:
            idx += 1
            continue
        name, end_name = parsed
        cursor = end_name
        while cursor < length and text[cursor].isspace():
            cursor += 1
        if cursor >= length or text[cursor] != "{":
            idx = end_name
            continue
        end_block = matching_brace(text, cursor)
        if end_block < 0:
            break
        rows.append((name, text[cursor + 1 : end_block]))
        idx = end_block + 1
    return rows


def parse_block_name(text: str, start: int) -> tuple[str, int] | None:
    if start >= len(text):
        return None
    first = text[start]
    if first == '"':
        end_quote = text.find('"', start + 1)
        if end_quote < 0:
            return None
        return text[start + 1 : end_quote], end_quote + 1
    if not (first.isalnum() or first == "_"):
        return None
    end_name = start + 1
    while end_name < len(text) and (
        text[end_name].isalnum() or text[end_name] in {"_", ".", "/", ":", "-", "+"}
    ):
        end_name += 1
    return text[start:end_name], end_name


def matching_brace(text: str, start: int) -> int:
    depth = 0
    for idx in range(start, len(text)):
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
            if depth == 0:
                return idx
    return -1


def first_block_body(text: str, name: str) -> str | None:
    for block_name, body in iter_named_blocks(text):
        if block_name == name:
            return body
    return None


def dedupe_criteria(rows: list[CriterionRow]) -> list[CriterionRow]:
    unique: dict[tuple[str, str], CriterionRow] = {}
    for row in rows:
        key = str(row.get("key", "")).strip()
        value = str(row.get("value", "")).strip()
        if not key:
            continue
        unique[(key, value)] = row
    return list(unique.values())


def inline_criteria(
    clean_text: str,
    log_text: str,
    *,
    log_lines: list[str] | None = None,
) -> list[CriterionRow]:
    rows: list[CriterionRow] = []
    for match in CRITERIA_RE.finditer(clean_text):
        key = match.group("key")
        if not KEY_TOKEN_RE.match(key):
            continue
        value = match.group("value").strip()
        status, evidence = criterion_status(key, log_text, log_lines=log_lines)
        rows.append({"key": key, "value": value, "status": status, "evidence": evidence})
    return rows


def runtime_control_conditions(
    clean_text: str,
    log_text: str,
    *,
    log_lines: list[str] | None = None,
) -> tuple[float | None, list[CriterionRow]]:
    start_time: float | None = None
    rows: list[CriterionRow] = []
    for key, body in iter_blocks_recursive(clean_text):
        block_type = first_match(body, TYPE_RE)
        if block_type is None or block_type.strip().strip('"') != "runTimeControl":
            continue
        if start_time is None:
            start_time = to_float(first_match(body, TIME_START_RE))
        rows.extend(runtime_control_block_rows(key, body, log_text, log_lines=log_lines))
    return start_time, rows


def runtime_control_block_rows(
    block_key: str,
    body: str,
    log_text: str,
    *,
    log_lines: list[str] | None = None,
) -> list[CriterionRow]:
    conditions = first_block_body(body, "conditions")
    if conditions is None:
        return []
    rows: list[CriterionRow] = []
    for cond_name, cond_body in iter_named_blocks(conditions):
        cond_type = (first_match(cond_body, TYPE_RE) or "condition").strip()
        cond_value = (first_match(cond_body, VALUE_RE) or cond_type).strip()
        field = first_match(cond_body, FIELD_RE) or first_match(cond_body, FIELDS_RE)
        key_parts = [block_key, cond_name, cond_type]
        if field:
            key_parts.append(field.strip())
        cond_key = ".".join(part for part in key_parts if part)
        status, evidence = criterion_status(cond_name, log_text, log_lines=log_lines)
        if status == "unknown":
            status, evidence = criterion_status(cond_type, log_text, log_lines=log_lines)
        rows.append(
            {
                "key": cond_key,
                "value": cond_value,
                "status": status,
                "evidence": evidence,
            },
        )
    return rows


def criterion_status(
    key: str,
    log_text: str,
    *,
    log_lines: list[str] | None = None,
) -> tuple[str, str | None]:
    needles = criterion_needles(key)
    lines = log_lines if log_lines is not None else log_text.splitlines()
    for raw in reversed(lines):
        line = raw.strip()
        lower = line.lower()
        if not any(needle in lower for needle in needles):
            continue
        if line_reports_conditions_not_met(lower):
            return "fail", line
        if line_reports_conditions_met(lower):
            return "pass", line
        if any(token in lower for token in ("not satisfied", "fail", "failed", "false", "exceed")):
            return "fail", line
        if any(token in lower for token in ("satisfied", "pass", "passed", "true")):
            return "pass", line
        return "unknown", line
    return "unknown", None


def enrich_criteria(
    rows: list[CriterionRow],
    log_text: str,
    *,
    log_lines: list[str] | None = None,
    criteria_start: float | None,
    latest_time: float | None,
    execution_times: list[float],
) -> list[CriterionRow]:
    if not rows:
        return rows
    lines = log_lines if log_lines is not None else log_text.splitlines()
    gate_status, gate_evidence = runtime_conditions_gate(lines)
    for row in rows:
        key = str(row.get("key", "")).strip()
        value = str(row.get("value", "")).strip()
        observed = criterion_observations(key, log_text, log_lines=lines)
        tolerance = to_float(first_float(value))
        comparator = criterion_comparator(key)
        delta_mode = criterion_uses_delta(key)

        live_value = observed[-1] if observed else None
        live_delta = rolling_band(observed[-6:]) if observed else None
        sample_count = len(observed)
        measured = live_delta if delta_mode and live_delta is not None else live_value

        status = str(row.get("status", "unknown")).strip().lower()
        if measured is not None and tolerance is not None and status == "unknown":
            if criterion_matches(measured, tolerance, comparator):
                if gate_status == "unmet":
                    if row.get("evidence") is None and gate_evidence:
                        row["evidence"] = gate_evidence
                else:
                    status = "pass"
            else:
                status = "fail"

        unmet_reason = criterion_unmet_reason(
            status=status,
            evidence=row.get("evidence"),
            criteria_start=criteria_start,
            latest_time=latest_time,
            samples=sample_count,
            minimum_samples=4 if delta_mode else 1,
        )
        eta_value = criterion_eta_seconds(
            observed,
            tolerance=tolerance,
            comparator=comparator,
            execution_times=execution_times,
            use_delta=delta_mode,
            status=status,
        )
        row["status"] = status
        row["live_value"] = live_value
        row["live_delta"] = live_delta
        row["tolerance"] = tolerance
        row["eta_seconds"] = eta_value
        row["unmet_reason"] = unmet_reason
        row["samples"] = sample_count
    return rows


def runtime_conditions_gate(lines: list[str]) -> tuple[str | None, str | None]:
    for raw in reversed(lines):
        line = raw.strip()
        lower = line.lower()
        if line_reports_conditions_not_met(lower):
            return "unmet", line
        if line_reports_conditions_met(lower):
            return "met", line
    return None, None


def line_reports_conditions_not_met(lower_line: str) -> bool:
    return any(token in lower_line for token in _CONDITIONS_NOT_MET_TOKENS)


def line_reports_conditions_met(lower_line: str) -> bool:
    if line_reports_conditions_not_met(lower_line):
        return False
    return any(token in lower_line for token in _CONDITIONS_MET_TOKENS)


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
        line = raw.strip()
        if not line:
            continue
        lower = line.lower()
        for needle in needles:
            at = lower.find(needle)
            if at < 0:
                continue
            value = float_after_index(line, at)
            if value is None:
                value = to_float(first_float(line))
            if value is None:
                break
            values.append(value)
            break
    return values


def criterion_needles(key: str) -> list[str]:
    if not key:
        return []
    needles: list[str] = []
    full = key.strip().lower()
    if full:
        needles.append(full)
    tokens = re.split(r"[./:\-]+", full)
    compact: list[str] = []
    for token in tokens:
        cleaned = "".join(ch for ch in token if ch.isalnum() or ch in {"_", "+"}).strip("_")
        if len(cleaned) < 3:
            continue
        if cleaned in _GENERIC_CRITERION_TOKENS:
            continue
        compact.append(cleaned)
        if cleaned not in needles:
            needles.append(cleaned)
    for idx in range(1, len(compact)):
        joined = f"{compact[idx - 1]} {compact[idx]}"
        if joined not in needles:
            needles.append(joined)
    # Longest needles first avoid generic token capturing unrelated numbers.
    needles.sort(key=len, reverse=True)
    return needles


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
    match_values = [int(match.group("value")) for match in ITER_RE.finditer(text)]
    if match_values:
        return match_values[-1]
    if fallback > 0:
        return fallback
    return None


def first_match(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return match.group("value").strip()


def last_float(text: str, pattern: re.Pattern[str]) -> float | None:
    values = [match.group("value") for match in pattern.finditer(text)]
    if not values:
        return None
    return to_float(values[-1])


def to_float(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().strip(";")
    try:
        return float(cleaned)
    except ValueError:
        return None
