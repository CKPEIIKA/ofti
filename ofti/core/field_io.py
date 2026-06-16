from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ofti.core.field_presets import resolve_field_preset
from ofti.core.times import PROCESSOR_RE, latest_time, processor_dirs
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
_BOUNDARY_RE = re.compile(r"\bboundaryField\s*\{(?P<body>.*)\}\s*$", re.DOTALL)
_NUMBER_RE = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|[-+]?inf|nan",
    re.IGNORECASE,
)


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
    if time_dir.is_dir():
        return time_dir
    # Decomposed parallel case: time directories live under processor*/. Return
    # the first processor's time dir; read_field_values aggregates across them.
    for proc in processor_dirs(case_path):
        candidate = proc / selected
        if candidate.is_dir():
            return candidate
    raise ValueError(f"time directory not found: {selected}")


def resolve_field_names(
    time_dir: Path,
    fields: list[str] | None,
    preset: str | None = None,
) -> list[str]:
    requested: list[str] = []
    if preset:
        requested.extend(resolve_field_preset(preset).fields)
    if fields:
        requested.extend(fields)
    if requested:
        return unique(requested)
    return sorted(
        path.name
        for path in time_dir.iterdir()
        if path.is_file() and foamlib_integration.is_field_file(path)
    )


def read_internal_field(path: Path) -> FieldData:
    return read_field_values(path, patch=None)


def read_field_values(path: Path, *, patch: str | None = None) -> FieldData:
    proc_paths = _decomposed_field_paths(path)
    if proc_paths is not None:
        return _read_field_aggregate(path.name, proc_paths, patch=patch)
    return _read_field_single(path, patch=patch)


def _decomposed_field_paths(path: Path) -> list[Path] | None:
    proc_dir = path.parent.parent
    if not PROCESSOR_RE.match(proc_dir.name):
        return None
    case_root = proc_dir.parent
    time_name = path.parent.name
    field_rel = path.name
    matches = [proc / time_name / field_rel for proc in processor_dirs(case_root)]
    existing = [candidate for candidate in matches if candidate.is_file()]
    return existing if len(existing) > 1 else None


def _read_field_aggregate(
    name: str,
    paths: list[Path],
    *,
    patch: str | None,
) -> FieldData:
    combined: list[tuple[float, ...]] = []
    for candidate in paths:
        try:
            data = _read_field_single(candidate, patch=patch)
        except ValueError:
            # A named patch may be absent on some subdomains (internal processor
            # boundaries); skip those and keep aggregating the rest.
            if patch is not None:
                continue
            raise
        combined.extend(data.values)
    if not combined:
        label = f"boundaryField.{patch}.value" if patch else "internalField"
        raise ValueError(f"unsupported or missing {label}: {name}")
    return FieldData(
        name=name,
        path=paths[0],
        kind=_field_kind_from_list(combined),
        values=combined,
        declared_count=len(combined),
        uniform=False,
    )


def _read_field_single(path: Path, *, patch: str | None = None) -> FieldData:
    if not path.is_file():
        raise ValueError(f"field not found: {path.name}")
    node_data = _field_from_foamlib(path, patch=patch)
    if node_data is not None:
        return node_data
    text = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
    if patch:
        text = _patch_value_text(text, patch)
    name = path.name
    uniform = _UNIFORM_RE.search(text) if patch is None else _uniform_value_match(text)
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
    nonuniform = _NONUNIFORM_RE.search(text) if patch is None else _nonuniform_value_match(text)
    if nonuniform:
        values = _parse_nonuniform_values(nonuniform.group("kind"), nonuniform.group("body"))
        declared = int(nonuniform.group("count"))
        if declared != len(values):
            raise ValueError(
                f"internalField count mismatch for {name}: "
                f"declared {declared}, parsed {len(values)}",
            )
        return FieldData(
            name=name,
            path=path,
            kind=_field_kind_from_list(values),
            values=values,
            declared_count=declared,
            uniform=False,
        )
    label = f"boundaryField.{patch}.value" if patch else "internalField"
    raise ValueError(f"unsupported or missing {label}: {name}")


def field_summary_row(data: FieldData) -> dict[str, object]:
    flat = flat_values(data.values)
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


def flat_values(values: list[tuple[float, ...]]) -> list[float]:
    return [item for row in values for item in row]


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _field_from_foamlib(path: Path, *, patch: str | None) -> FieldData | None:
    if not (foamlib_integration.available() and foamlib_integration.is_field_file(path)):
        return None
    try:
        key = "internalField" if patch is None else f"boundaryField.{patch}.value"
        node = foamlib_integration.read_field_entry_node(path, key)
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


def _patch_value_text(text: str, patch: str) -> str:
    boundary = _BOUNDARY_RE.search(text)
    if not boundary:
        raise ValueError(f"boundaryField missing patch: {patch}")
    span = _named_block_span(boundary.group("body"), patch)
    if span is None:
        raise ValueError(f"boundaryField missing patch: {patch}")
    return boundary.group("body")[span[0] : span[1]]


def _named_block_span(text: str, name: str) -> tuple[int, int] | None:
    match = re.search(rf"\b{re.escape(name)}\s*\{{", text)
    if not match:
        return None
    start = match.end()
    depth = 1
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index
    return None


def _uniform_value_match(text: str) -> re.Match[str] | None:
    return re.search(r"\bvalue\s+uniform\s+(?P<value>[^;]+);", text, re.DOTALL)


def _nonuniform_value_match(text: str) -> re.Match[str] | None:
    return re.search(
        r"\bvalue\s+nonuniform\s+List<(?P<kind>[^>]+)>\s+"
        r"(?P<count>\d+)\s*\((?P<body>.*?)\)\s*;",
        text,
        re.DOTALL,
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
