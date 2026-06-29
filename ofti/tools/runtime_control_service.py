from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TypedDict

from ofti.core.case_snapshot import write_case_snapshot
from ofti.core.tool_dicts_service import apply_assignment_or_write
from ofti.foamlib.logs import (
    execution_time_deltas,
    parse_log_metrics,
    parse_log_metrics_and_residuals,
    read_log_text,
    read_log_text_filtered,
)
from ofti.tools.runtime_criteria import (
    criterion_comparator,
    criterion_eta_seconds,
    criterion_matches,
    criterion_needles,
    criterion_observations,
    criterion_unmet_reason,
    criterion_uses_delta,
    eta_seconds,
    first_float,
    first_match,
    is_log_fresh,
    latest_iteration,
    rolling_band,
    to_float,
)

DELTA_T_RE = re.compile(r"\bdeltaT\s*=\s*(?P<value>[0-9eE.+-]+)", re.IGNORECASE)
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
_CONDITIONS_NOT_MET_TOKENS = ("conditions not met", "condition not met")
_CONDITIONS_MET_TOKENS = ("conditions met", "condition met")
_CONTROL_EDIT_KEYS = {"stopAt", "startFrom", "endTime", "deltaT", "writeInterval"}


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


class ControlDictEditPayload(TypedDict):
    case: str
    path: str
    ok: bool
    applied: bool
    blocked: bool
    snapshot_path: str | None
    updates: list[dict[str, str]]
    diff: list[str]
    failures: list[str]
    error: str | None


def runtime_control_snapshot(
    case_path: Path,
    solver: str | None,
    *,
    resolve_log_source_fn: Callable[[Path], Path],
    log_path_hint: Path | None = None,
    lightweight: bool = False,
    max_log_bytes: int | None = None,
) -> RuntimeControlSnapshot:
    log_path = resolve_solver_log(
        case_path,
        solver,
        resolve_log_source_fn=resolve_log_source_fn,
        log_path_hint=log_path_hint,
    )
    text = _runtime_snapshot_text(
        case_path,
        log_path,
        lightweight=lightweight,
        max_log_bytes=max_log_bytes,
    )
    metrics, residuals = _runtime_snapshot_metrics(text, lightweight=lightweight)
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


def _runtime_snapshot_text(
    case_path: Path,
    log_path: Path | None,
    *,
    lightweight: bool,
    max_log_bytes: int | None,
) -> str:
    if log_path is None:
        return ""
    read_limit = max_log_bytes
    if read_limit is None and lightweight:
        read_limit = 2 * 1024 * 1024
    if lightweight or read_limit is not None:
        return read_log_text(log_path, max_bytes=read_limit)
    return read_log_text_filtered(log_path, terms=runtime_log_terms(case_path))


def _runtime_snapshot_metrics(text: str, *, lightweight: bool):
    if not text:
        return parse_log_metrics(""), {}
    if lightweight:
        return parse_log_metrics(text), {}
    return parse_log_metrics_and_residuals(text)


def control_dict_edit_payload(
    case_path: Path,
    updates: dict[str, str],
    *,
    write_snapshot: bool = False,
    apply: bool = False,
) -> ControlDictEditPayload:
    """Plan or apply a small, safe runtime edit to system/controlDict.

    Applying is intentionally blocked unless a case snapshot is written in the
    same call. This keeps live-run mutation paths explicit and recoverable.
    """
    control_dict = case_path / "system" / "controlDict"
    if error := _control_edit_precheck(case_path, control_dict, updates):
        return error
    rows = _control_edit_rows(control_dict, updates)
    diff = _control_edit_diff(rows)
    snapshot_path, error = _control_edit_snapshot(case_path, write_snapshot)
    if error is not None:
        return _control_edit_error(case_path, error, updates=rows, diff=diff)
    blocked = bool(apply and snapshot_path is None)
    failures = _apply_control_edits(case_path, control_dict, rows) if apply and not blocked else []
    return {
        "case": str(case_path),
        "path": "system/controlDict",
        "ok": not failures and not blocked,
        "applied": bool(apply and not failures and not blocked),
        "blocked": blocked,
        "snapshot_path": str(snapshot_path) if snapshot_path is not None else None,
        "updates": rows,
        "diff": diff,
        "failures": failures,
        "error": "snapshot required before applying runtime edits" if blocked else None,
    }


def _control_edit_precheck(
    case_path: Path,
    control_dict: Path,
    updates: dict[str, str],
) -> ControlDictEditPayload | None:
    if not control_dict.is_file():
        return _control_edit_error(case_path, "system/controlDict is missing")
    if not updates:
        return _control_edit_error(case_path, "no controlDict updates requested")
    invalid = sorted(set(updates) - _CONTROL_EDIT_KEYS)
    if invalid:
        return _control_edit_error(
            case_path,
            f"unsupported controlDict keys: {', '.join(invalid)}",
        )
    return None


def _control_edit_rows(control_dict: Path, updates: dict[str, str]) -> list[dict[str, str]]:
    current = _control_dict_values(control_dict, updates.keys())
    return [
        {
            "key": key,
            "old": current.get(key) or "<missing>",
            "new": str(value),
            "path": "system/controlDict",
        }
        for key, value in sorted(updates.items())
    ]


def _control_edit_snapshot(case_path: Path, write_snapshot: bool) -> tuple[Path | None, str | None]:
    if not write_snapshot:
        return None, None
    try:
        return write_case_snapshot(case_path), None
    except (OSError, RuntimeError, ValueError) as exc:
        return None, str(exc)


def _apply_control_edits(
    case_path: Path,
    control_dict: Path,
    rows: list[dict[str, str]],
) -> list[str]:
    failures: list[str] = []
    for row in rows:
        key = row["key"]
        if not _apply_control_dict_edit(case_path, control_dict, key, row["new"]):
            failures.append(key)
    return failures


def resolve_solver_log(
    case_path: Path,
    solver: str | None,
    *,
    resolve_log_source_fn: Callable[[Path], Path],
    log_path_hint: Path | None = None,
) -> Path | None:
    if solver:
        candidate = case_path / f"log.{solver}"
        if candidate.is_file():
            return candidate.resolve()
    if log_path_hint is not None and log_path_hint.is_file():
        return log_path_hint.resolve()
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
    terms = _inline_runtime_log_terms(clean_text)
    terms.extend(_runtime_control_log_terms(clean_text))
    terms.extend(["runTimeControl", "condition", "conditions"])
    return terms


def _inline_runtime_log_terms(clean_text: str) -> list[str]:
    return [
        match.group("key").strip()
        for match in CRITERIA_RE.finditer(clean_text)
        if match.group("key").strip()
    ]


def _runtime_control_log_terms(clean_text: str) -> list[str]:
    terms: list[str] = []
    for _block_key, row in runtime_control_term_rows(clean_text):
        terms.extend(term for term in row if term)
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
    include_path = _expanded_include_path(include_raw, case_root)
    if include_path.is_absolute():
        return include_path
    if include_kind == "includeEtc":
        return _resolve_include_etc(include_path)
    return (include_parent / include_path).resolve()


def _expanded_include_path(include_raw: str, case_root: Path) -> Path:
    expanded = os.path.expandvars(include_raw.replace("$FOAM_CASE", str(case_root)))
    return Path(expanded).expanduser()


def _include_etc_roots() -> list[Path]:
    roots: list[Path] = []
    if foam_etc := os.environ.get("FOAM_ETC"):
        roots.append(Path(foam_etc))
    if wm_project_dir := os.environ.get("WM_PROJECT_DIR"):
        roots.append(Path(wm_project_dir) / "etc")
    return roots


def _resolve_include_etc(include_path: Path) -> Path | None:
    roots = _include_etc_roots()
    for root in roots:
        candidate = (root / include_path).resolve()
        if candidate.exists():
            return candidate
    if roots:
        return (roots[0] / include_path).resolve()
    return None


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
        _enrich_criterion_row(
            row,
            log_text,
            lines=lines,
            gate=(gate_status, gate_evidence),
            criteria_start=criteria_start,
            latest_time=latest_time,
            execution_times=execution_times,
        )
    return rows


def _enrich_criterion_row(
    row: CriterionRow,
    log_text: str,
    *,
    lines: list[str],
    gate: tuple[str | None, str | None],
    criteria_start: float | None,
    latest_time: float | None,
    execution_times: list[float],
) -> None:
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
    status = _criterion_status_from_measurement(
        row,
        measured=measured,
        tolerance=tolerance,
        comparator=comparator,
        gate=gate,
    )
    row["status"] = status
    row["live_value"] = live_value
    row["live_delta"] = live_delta
    row["tolerance"] = tolerance
    row["eta_seconds"] = criterion_eta_seconds(
        observed,
        tolerance=tolerance,
        comparator=comparator,
        execution_times=execution_times,
        use_delta=delta_mode,
        status=status,
    )
    row["unmet_reason"] = criterion_unmet_reason(
        status=status,
        evidence=row.get("evidence"),
        criteria_start=criteria_start,
        latest_time=latest_time,
        samples=sample_count,
        minimum_samples=4 if delta_mode else 1,
    )
    row["samples"] = sample_count


def _criterion_status_from_measurement(
    row: CriterionRow,
    *,
    measured: float | None,
    tolerance: float | None,
    comparator: str,
    gate: tuple[str | None, str | None],
) -> str:
    status = str(row.get("status", "unknown")).strip().lower()
    if measured is None or tolerance is None or status != "unknown":
        return status
    if not criterion_matches(measured, tolerance, comparator):
        return "fail"
    gate_status, gate_evidence = gate
    if gate_status == "unmet":
        if row.get("evidence") is None and gate_evidence:
            row["evidence"] = gate_evidence
        return status
    return "pass"


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


def _control_dict_values(path: Path, keys: Iterable[str]) -> dict[str, str | None]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""
    return {str(key): _control_entry_value(text, str(key)) for key in keys}


def _control_entry_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s+([^;]+);", text)
    return match.group(1).strip() if match else None


def _apply_control_dict_edit(case_path: Path, path: Path, key: str, value: str) -> bool:
    if apply_assignment_or_write(case_path, path, [key], value):
        return True
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    pattern = re.compile(rf"(?m)^(\s*{re.escape(key)}\s+)([^;]+)(;)")
    replacement = rf"\g<1>{value}\g<3>"
    if pattern.search(text):
        updated = pattern.sub(replacement, text, count=1)
    else:
        updated = text.rstrip() + f"\n{key} {value};\n"
    try:
        path.write_text(updated, encoding="utf-8")
    except OSError:
        return False
    return True


def _control_edit_diff(rows: list[dict[str, str]]) -> list[str]:
    lines = ["--- current system/controlDict", "+++ proposed system/controlDict"]
    for row in rows:
        old = row["old"]
        new = row["new"]
        key = row["key"]
        if old == "<missing>":
            lines.append(f"+{key} {new};")
        else:
            lines.append(f"-{key} {old};")
            lines.append(f"+{key} {new};")
    return lines


def _control_edit_error(
    case_path: Path,
    error: str,
    *,
    updates: list[dict[str, str]] | None = None,
    diff: list[str] | None = None,
) -> ControlDictEditPayload:
    return {
        "case": str(case_path),
        "path": "system/controlDict",
        "ok": False,
        "applied": False,
        "blocked": False,
        "snapshot_path": None,
        "updates": updates or [],
        "diff": diff or [],
        "failures": [],
        "error": error,
    }


def last_float(text: str, pattern: re.Pattern[str]) -> float | None:
    values = [match.group("value") for match in pattern.finditer(text)]
    if not values:
        return None
    return to_float(values[-1])
