from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.times import latest_time
from ofti.foamlib import adapter as foamlib_integration

_COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE_RE = re.compile(r"//.*?$", re.MULTILINE)
_UNIFORM_RE = re.compile(r"\binternalField\s+uniform\s+(?P<value>[^;]+);", re.DOTALL)
_NONUNIFORM_RE = re.compile(
    r"\binternalField\s+nonuniform\s+List<(?P<kind>[^>]+)>\s+"
    r"(?P<count>\d+)\s*\((?P<body>.*?)\)\s*;",
    re.DOTALL,
)
_VECTOR_RE = re.compile(r"\(([^()]*)\)")
_NUMBER_RE = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|[-+]?inf|nan",
    re.IGNORECASE,
)

FIELD_PRESETS: dict[str, list[str]] = {
    "air5": ["N2", "O2", "NO", "N", "O", "Tt", "Tv", "p", "rho"],
    "air11": [
        "N2",
        "O2",
        "NO",
        "N",
        "O",
        "N2+",
        "O2+",
        "NO+",
        "N+",
        "O+",
        "e-",
        "Tt",
        "Tv",
        "p",
        "rho",
    ],
    "flow": ["p", "Tt", "Tv", "U", "rho"],
}

_SPECIES_NAMES = {
    "N2",
    "O2",
    "NO",
    "N",
    "O",
    "N2+",
    "O2+",
    "NO+",
    "N+",
    "O+",
    "e-",
    "E",
}
_NONNEGATIVE_EXACT = {
    "rho",
    "p",
    "k",
    "epsilon",
    "omega",
    "T",
    "Tt",
    "Tv",
    "Tr",
    "N2",
    "O2",
    "NO",
    "N",
    "O",
    "N2+",
    "O2+",
    "NO+",
    "N+",
    "O+",
    "e-",
}


@dataclass(frozen=True)
class FieldData:
    name: str
    path: Path
    kind: str
    values: list[tuple[float, ...]]
    declared_count: int | None
    uniform: bool

    @property
    def component_count(self) -> int:
        if not self.values:
            return 0
        return len(self.values[0])

    @property
    def count(self) -> int:
        return len(self.values)


def resolve_time_dir(case_path: Path, time_name: str) -> Path:
    selected = latest_time(case_path) if time_name == "latest" else time_name
    time_dir = case_path / selected
    if not time_dir.is_dir():
        raise ValueError(f"time directory not found: {selected}")
    return time_dir


def resolve_field_names(
    time_dir: Path,
    fields: list[str] | None,
    preset: str | None = None,
) -> list[str]:
    requested: list[str] = []
    if preset:
        try:
            requested.extend(FIELD_PRESETS[preset])
        except KeyError as exc:
            raise ValueError(f"unknown field preset: {preset}") from exc
    if fields:
        requested.extend(fields)
    if requested:
        return _unique(requested)
    return sorted(
        path.name
        for path in time_dir.iterdir()
        if path.is_file() and foamlib_integration.is_field_file(path)
    )


def read_internal_field(path: Path) -> FieldData:
    if not path.is_file():
        raise ValueError(f"field not found: {path.name}")
    node_data = _field_from_foamlib(path)
    if node_data is not None:
        return node_data
    text = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
    name = path.name
    uniform = _UNIFORM_RE.search(text)
    if uniform:
        values = _parse_value(uniform.group("value"))
        if not values:
            raise ValueError(f"internalField has no numeric values: {name}")
        return FieldData(
            name=name,
            path=path,
            kind=_field_kind(values),
            values=[values],
            declared_count=1,
            uniform=True,
        )
    nonuniform = _NONUNIFORM_RE.search(text)
    if nonuniform:
        values = _parse_nonuniform_values(nonuniform.group("kind"), nonuniform.group("body"))
        declared = int(nonuniform.group("count"))
        if declared != len(values):
            message = (
                f"internalField count mismatch for {name}: "
                f"declared {declared}, parsed {len(values)}"
            )
            raise ValueError(
                message,
            )
        return FieldData(
            name=name,
            path=path,
            kind=_field_kind_from_list(values),
            values=values,
            declared_count=declared,
            uniform=False,
        )
    raise ValueError(f"unsupported or missing internalField: {name}")


def field_sanity_payload(
    case_path: Path,
    *,
    time_name: str = "latest",
    fields: list[str] | None = None,
) -> dict[str, Any]:
    time_dir = resolve_time_dir(case_path, time_name)
    names = resolve_field_names(time_dir, fields)
    rows: list[dict[str, Any]] = []
    hard_errors: list[str] = []
    violations: list[dict[str, Any]] = []
    species: dict[str, FieldData] = {}
    for name in names:
        try:
            data = read_internal_field(time_dir / name)
        except (OSError, ValueError) as exc:
            hard_errors.append(str(exc))
            rows.append({"field": name, "ok": False, "error": str(exc)})
            continue
        row = _field_summary_row(data)
        rows.append(row)
        if row["nonfinite_count"]:
            hard_errors.append(f"{name}: nonfinite values={row['nonfinite_count']}")
        if _nonnegative_field(name) and row["negative_count"]:
            violations.append({"field": name, "kind": "negative", "count": row["negative_count"]})
        if _species_field(name) and data.component_count == 1:
            species[name] = data
    species_sum = _species_sum_payload(species)
    species_deviation = species_sum["max_abs_deviation"] if species_sum else None
    if isinstance(species_deviation, (int, float)) and species_deviation > 1e-8:
        violations.append(
            {
                "field": "sum(Y)",
                "kind": "species_sum",
                "max_abs_deviation": species_deviation,
            },
        )
    return {
        "case": str(case_path),
        "time": time_dir.name,
        "time_dir": str(time_dir),
        "fields_requested": names,
        "field_count": len(rows),
        "ok": not hard_errors,
        "physical_ok": not violations and not hard_errors,
        "hard_errors": hard_errors,
        "violations": violations,
        "fields": rows,
        "species_sum": species_sum,
    }


def compare_fields_payload(
    left_case: Path,
    right_case: Path,
    *,
    time_name: str = "latest",
    fields: list[str] | None = None,
    preset: str | None = None,
) -> dict[str, Any]:
    left_time = resolve_time_dir(left_case, time_name)
    right_time = resolve_time_dir(right_case, time_name)
    names = resolve_field_names(left_time, fields, preset=preset)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for name in names:
        try:
            left = read_internal_field(left_time / name)
            right = read_internal_field(right_time / name)
            row = _compare_field_data(left, right)
        except (OSError, ValueError) as exc:
            row = {"field": name, "ok": False, "error": str(exc)}
            errors.append(f"{name}: {exc}")
        rows.append(row)
    return {
        "left_case": str(left_case),
        "right_case": str(right_case),
        "time": left_time.name,
        "right_time": right_time.name,
        "preset": preset,
        "fields_requested": names,
        "field_count": len(rows),
        "ok": not errors,
        "same": not errors and all(float(row.get("max_abs", 0.0) or 0.0) == 0.0 for row in rows),
        "errors": errors,
        "fields": rows,
    }


def split_field_list(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    names: list[str] = []
    for value in values:
        names.extend(part.strip() for part in value.split(",") if part.strip())
    return _unique(names)


def _field_from_foamlib(path: Path) -> FieldData | None:
    if not (foamlib_integration.available() and foamlib_integration.is_field_file(path)):
        return None
    try:
        node = foamlib_integration.read_field_entry_node(path, "internalField")
    except Exception:
        return None
    values = _coerce_numeric_values(node)
    if not values:
        return None
    if _looks_like_scalar_list_ambiguous(path, values):
        return None
    return FieldData(
        name=path.name,
        path=path,
        kind=_field_kind_from_list(values),
        values=values,
        declared_count=len(values),
        uniform=len(values) == 1,
    )


def _looks_like_scalar_list_ambiguous(path: Path, values: list[tuple[float, ...]]) -> bool:
    if len(values) != 1 or len(values[0]) <= 1:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "nonuniform" in text and "List<scalar>" in text


def _coerce_numeric_values(node: object) -> list[tuple[float, ...]]:
    if isinstance(node, bool):
        return []
    if isinstance(node, (int, float)):
        return [(float(node),)]
    tolist = getattr(node, "tolist", None)
    if callable(tolist):
        try:
            node = tolist()
        except Exception:
            return []
    if isinstance(node, (list, tuple)):
        return _coerce_numeric_sequence(node)
    return [(float(node),)] if isinstance(node, (int, float)) else []


def _coerce_numeric_sequence(node: Sequence[object]) -> list[tuple[float, ...]]:
    if not node:
        return []
    if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in node):
        values: list[float] = []
        for item in node:
            if not isinstance(item, (int, float)) or isinstance(item, bool):
                return []
            values.append(float(item))
        return [tuple(values)]
    rows: list[tuple[float, ...]] = []
    for item in node:
        rows.extend(_coerce_numeric_values(item))
    return rows


def _strip_comments(text: str) -> str:
    return _COMMENT_LINE_RE.sub("", _COMMENT_BLOCK_RE.sub("", text))


def _parse_value(text: str) -> tuple[float, ...]:
    return tuple(float(token) for token in _NUMBER_RE.findall(text))


def _parse_nonuniform_values(kind: str, body: str) -> list[tuple[float, ...]]:
    if "vector" in kind.lower():
        return [_parse_value(match.group(1)) for match in _VECTOR_RE.finditer(body)]
    return [(float(token),) for token in _NUMBER_RE.findall(body)]


def _field_kind(values: tuple[float, ...]) -> str:
    if len(values) == 1:
        return "scalar"
    if len(values) in {2, 3}:
        return "vector"
    return "numeric"


def _field_kind_from_list(values: list[tuple[float, ...]]) -> str:
    if not values:
        return "empty"
    sizes = {len(row) for row in values}
    if sizes == {1}:
        return "scalar"
    if sizes <= {2, 3}:
        return "vector"
    return "numeric"


def _field_summary_row(data: FieldData) -> dict[str, Any]:
    flat = _flat_values(data.values)
    finite = [value for value in flat if math.isfinite(value)]
    return {
        "field": data.name,
        "ok": True,
        "kind": data.kind,
        "uniform": data.uniform,
        "count": data.count,
        "components": data.component_count,
        "value_count": len(flat),
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "negative_count": sum(1 for value in finite if value < 0.0),
        "nonfinite_count": len(flat) - len(finite),
    }


def _compare_field_data(left: FieldData, right: FieldData) -> dict[str, Any]:
    left_values, right_values = _align_values(left, right)
    max_abs = 0.0
    max_rel = 0.0
    nonfinite = 0
    compared = 0
    for left_row, right_row in zip(left_values, right_values, strict=True):
        if len(left_row) != len(right_row):
            raise ValueError(
                f"component mismatch for {left.name}: {len(left_row)} vs {len(right_row)}",
            )
        for left_value, right_value in zip(left_row, right_row, strict=True):
            compared += 1
            if not (math.isfinite(left_value) and math.isfinite(right_value)):
                nonfinite += 1
                continue
            diff = abs(left_value - right_value)
            denom = max(abs(left_value), abs(right_value), 1e-300)
            max_abs = max(max_abs, diff)
            max_rel = max(max_rel, diff / denom)
    return {
        "field": left.name,
        "ok": True,
        "kind": left.kind if left.kind == right.kind else f"{left.kind}/{right.kind}",
        "left_count": left.count,
        "right_count": right.count,
        "components": left.component_count,
        "count": compared,
        "max_abs": max_abs,
        "max_rel": max_rel,
        "nonfinite_pairs": nonfinite,
    }


def _align_values(
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


def _flat_values(values: list[tuple[float, ...]]) -> list[float]:
    return [item for row in values for item in row]


def _nonnegative_field(name: str) -> bool:
    return name in _NONNEGATIVE_EXACT or name.startswith(("T", "eV")) or _species_field(name)


def _species_field(name: str) -> bool:
    return name in _SPECIES_NAMES


def _species_sum_payload(species: dict[str, FieldData]) -> dict[str, Any] | None:
    if not species:
        return None
    count = max((data.count for data in species.values()), default=0)
    if count <= 0:
        return None
    sums: list[float] = []
    for index in range(count):
        total = 0.0
        for data in species.values():
            if not data.uniform and data.count != count:
                return {
                    "fields": sorted(species),
                    "count": 0,
                    "min": None,
                    "max": None,
                    "max_abs_deviation": None,
                    "error": "species field counts differ",
                }
            row = data.values[0] if data.uniform else data.values[index]
            total += row[0]
        sums.append(total)
    deviations = [abs(value - 1.0) for value in sums if math.isfinite(value)]
    return {
        "fields": sorted(species),
        "count": len(sums),
        "min": min(sums),
        "max": max(sums),
        "max_abs_deviation": max(deviations) if deviations else None,
    }


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
