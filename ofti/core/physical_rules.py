from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.field_io import (
    FieldData,
    field_summary_row,
    flat_values,
    read_field_values,
    resolve_field_names,
    resolve_time_dir,
    unique,
)

_NONNEGATIVE_EXACT = {
    "rho",
    "p",
    "k",
    "epsilon",
    "omega",
    "T",
}


@dataclass(frozen=True)
class FieldRule:
    name: str
    finite: bool = True
    min_value: float | None = None
    max_value: float | None = None


def field_sanity_payload(
    case_path: Path,
    *,
    time_name: str = "latest",
    fields: list[str] | None = None,
    rules: list[FieldRule] | None = None,
    patch: str | None = None,
) -> dict[str, Any]:
    time_dir = resolve_time_dir(case_path, time_name)
    names = field_names_for_rules(time_dir, fields, rules)
    rule_map = {rule.name: rule for rule in rules or []}
    rows: list[dict[str, Any]] = []
    hard_errors: list[str] = []
    violations: list[dict[str, Any]] = []
    for name in names:
        try:
            data = read_field_values(time_dir / name, patch=patch)
        except (OSError, ValueError) as exc:
            hard_errors.append(str(exc))
            rows.append({"field": name, "ok": False, "error": str(exc)})
            continue
        row = field_summary_row(data)
        rows.append(row)
        rule = rule_map.get(name)
        if finite_required(rule) and row["nonfinite_count"]:
            hard_errors.append(f"{name}: nonfinite values={row['nonfinite_count']}")
        violations.extend(rule_violations(name, data, row, rule))
    return {
        "case": str(case_path),
        "time": time_dir.name,
        "time_dir": str(time_dir),
        "patch": patch,
        "fields_requested": names,
        "field_count": len(rows),
        "ok": not hard_errors,
        "physical_ok": not violations and not hard_errors,
        "hard_errors": hard_errors,
        "violations": violations,
        "fields": rows,
    }


def parse_field_rules(values: list[str] | None) -> list[FieldRule]:
    rules: list[FieldRule] = []
    for value in values or []:
        rules.append(_parse_field_rule(value))
    return rules


def _parse_field_rule(value: str) -> FieldRule:
    if ":" not in value:
        return FieldRule(name=value.strip())
    name, raw_checks = value.split(":", 1)
    finite, min_value, max_value = _parse_rule_checks(raw_checks)
    return FieldRule(
        name=name.strip(),
        finite=finite,
        min_value=min_value,
        max_value=max_value,
    )


def _parse_rule_checks(raw_checks: str) -> tuple[bool, float | None, float | None]:
    # Finite checking is on by default: `rho:min=0` should reject NaN/Inf
    # just like a bare `rho` rule. Use `nofinite` or `finite=false` to skip.
    finite = True
    min_value: float | None = None
    max_value: float | None = None
    for part in raw_checks.split(","):
        key, _, raw = part.strip().partition("=")
        finite, min_value, max_value = _updated_rule_check(
            key,
            raw,
            finite=finite,
            min_value=min_value,
            max_value=max_value,
        )
    return finite, min_value, max_value


def _updated_rule_check(
    key: str,
    raw: str,
    *,
    finite: bool,
    min_value: float | None,
    max_value: float | None,
) -> tuple[bool, float | None, float | None]:
    if key == "finite":
        return (_truthy(raw) if raw else True), min_value, max_value
    if key == "nofinite":
        return False, min_value, max_value
    if key == "min":
        return finite, float(raw), max_value
    if key == "max":
        return finite, min_value, float(raw)
    return finite, min_value, max_value


def field_names_for_rules(
    time_dir: Path,
    fields: list[str] | None,
    rules: list[FieldRule] | None,
) -> list[str]:
    explicit = fields or [rule.name for rule in rules or []]
    if explicit:
        return unique(explicit)
    return resolve_field_names(time_dir, None)


def finite_required(rule: FieldRule | None) -> bool:
    return rule.finite if rule is not None else True


def _truthy(raw: str) -> bool:
    return raw.strip().lower() not in {"false", "0", "no", "off"}


def rule_violations(
    name: str,
    data: FieldData,
    row: dict[str, Any],
    rule: FieldRule | None,
) -> list[dict[str, Any]]:
    values = [value for value in flat_values(data.values) if math.isfinite(value)]
    min_value = rule.min_value if rule else (0.0 if nonnegative_field(name) else None)
    max_value = rule.max_value if rule else (1.0 if name.startswith("alpha") else None)
    violations: list[dict[str, Any]] = []
    if min_value is not None:
        bad = [index for index, value in enumerate(values) if value < min_value]
        if bad:
            violations.append(
                {
                    "field": name,
                    "kind": f"min>={min_value:g}",
                    "count": len(bad),
                    "sample": bad[:10],
                },
            )
    elif row["negative_count"]:
        violations.append({"field": name, "kind": "negative", "count": row["negative_count"]})
    if max_value is not None:
        bad = [index for index, value in enumerate(values) if value > max_value]
        if bad:
            violations.append(
                {
                    "field": name,
                    "kind": f"max<={max_value:g}",
                    "count": len(bad),
                    "sample": bad[:10],
                },
            )
    return violations


def nonnegative_field(name: str) -> bool:
    return name in _NONNEGATIVE_EXACT
