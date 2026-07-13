from __future__ import annotations

import math
import re
import struct
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
_BINARY_HEADER_RE = re.compile(rb"\bFoamFile\s*\{(?P<body>.*?)\}", re.DOTALL)
_BINARY_ARCH_RE = re.compile(rb'\barch\s+"(?P<arch>[^"]+)"\s*;')
_BINARY_INTERNAL_RE = re.compile(
    rb"\binternalField\s+nonuniform\s+List<(?P<kind>[^>]+)>\s+(?P<count>\d+)\s*\(",
    re.DOTALL,
)
_BINARY_COMPONENTS = {"scalar": 1, "sphericaltensor": 1, "vector": 3, "symmtensor": 6, "tensor": 9}


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
        path.name for path in time_dir.iterdir() if path.is_file() and foamlib_integration.is_field_file(path)
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
    if existing and len(existing) != len(matches):
        missing = [candidate.parent.parent.name for candidate in matches if not candidate.is_file()]
        raise ValueError(
            f"incomplete decomposed field {field_rel} at {time_name}; missing in {', '.join(missing)}",
        )
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
    payload = path.read_bytes()
    if _binary_field(payload):
        return _read_binary_field(path, payload, patch=patch)
    node_data = _field_from_foamlib(path, patch=patch)
    if node_data is not None:
        return node_data
    text = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
    if patch:
        text = _patch_value_text(text, patch)
    text_match = _field_text_match(text, patch=patch)
    if text_match is not None:
        return _field_data_from_match(path, text_match)
    label = f"boundaryField.{patch}.value" if patch else "internalField"
    raise ValueError(f"unsupported or missing {label}: {path.name}")


def _binary_field(payload: bytes) -> bool:
    header = _BINARY_HEADER_RE.search(payload)
    return bool(header and re.search(rb"\bformat\s+binary\s*;", header.group("body")))


def _read_binary_field(path: Path, payload: bytes, *, patch: str | None) -> FieldData:
    if patch is not None:
        raise ValueError(f"unsupported_binary_format: boundary patch values are not supported for {path.name}")
    match = _BINARY_INTERNAL_RE.search(payload)
    if match is None:
        return _read_binary_uniform_field(path, payload)
    kind = match.group("kind").decode("ascii", errors="strict").strip()
    count = int(match.group("count"))
    endian, scalar_code, scalar_size = _binary_scalar_layout(path, payload)
    components = _binary_component_count(path, kind)
    byte_count = count * components * scalar_size
    start = match.end()
    end = start + byte_count
    if end > len(payload) or not payload[end:].lstrip().startswith(b");"):
        raise ValueError(f"invalid_binary_field_payload: truncated internalField for {path.name}")
    values = _unpack_binary_rows(payload[start:end], endian, scalar_code, components)
    return FieldData(path.name, path, _field_kind_from_list(values), values, count, False)


def _read_binary_uniform_field(path: Path, payload: bytes) -> FieldData:
    text = _strip_comments(payload.decode("utf-8", errors="ignore"))
    match = _UNIFORM_RE.search(text)
    if match is None:
        raise ValueError(f"unsupported_binary_format: internalField layout for {path.name}")
    return _uniform_field_data(path, match.group("value"))


def _binary_scalar_layout(path: Path, payload: bytes) -> tuple[str, str, int]:
    header = _BINARY_HEADER_RE.search(payload)
    arch = _BINARY_ARCH_RE.search(header.group("body")) if header else None
    if arch is None:
        raise ValueError(f"unsupported_binary_format: missing arch metadata for {path.name}")
    entries = _binary_arch_entries(arch.group("arch").decode("ascii", errors="strict"))
    byte_order = entries.get("byte_order")
    if byte_order not in {"LSB", "MSB"} or entries.get("label") not in {"32", "64"}:
        raise ValueError(f"unsupported_binary_format: arch metadata for {path.name}")
    endian = "<" if byte_order == "LSB" else ">"
    scalar_bits = entries.get("scalar")
    if scalar_bits == "32":
        return endian, "f", 4
    if scalar_bits == "64":
        return endian, "d", 8
    raise ValueError(f"unsupported_binary_format: scalar size {scalar_bits!r} for {path.name}")


def _binary_arch_entries(arch: str) -> dict[str, str]:
    parts = [part.strip() for part in arch.split(";") if part.strip()]
    entries = {"byte_order": parts[0]} if parts else {}
    entries.update(dict(part.split("=", 1) for part in parts[1:] if "=" in part))
    return entries


def _binary_component_count(path: Path, kind: str) -> int:
    components = _BINARY_COMPONENTS.get(kind.lower())
    if components is None:
        raise ValueError(f"unsupported_binary_format: List<{kind}> for {path.name}")
    return components


def _unpack_binary_rows(payload: bytes, endian: str, scalar_code: str, components: int) -> list[tuple[float, ...]]:
    scalar_size = struct.calcsize(scalar_code)
    row_size = scalar_size * components
    row_format = f"{endian}{components}{scalar_code}"
    complete_payload = payload[: len(payload) // row_size * row_size]
    return [tuple(float(value) for value in row) for row in struct.iter_unpack(row_format, complete_payload)]


def _field_text_match(text: str, *, patch: str | None) -> re.Match[str] | None:
    uniform = _UNIFORM_RE.search(text) if patch is None else _uniform_value_match(text)
    if uniform:
        return uniform
    return _NONUNIFORM_RE.search(text) if patch is None else _nonuniform_value_match(text)


def _field_data_from_match(path: Path, match: re.Match[str]) -> FieldData:
    if "value" in match.groupdict():
        return _uniform_field_data(path, match.group("value"))
    return _nonuniform_field_data(path, match)


def _uniform_field_data(path: Path, raw_value: str) -> FieldData:
    values = _parse_value(raw_value)
    if not values:
        raise ValueError(f"internalField has no numeric values: {path.name}")
    return FieldData(
        name=path.name,
        path=path,
        kind=_field_kind(values),
        values=[values],
        declared_count=1,
        uniform=True,
    )


def _nonuniform_field_data(path: Path, match: re.Match[str]) -> FieldData:
    values = _parse_nonuniform_values(match.group("kind"), match.group("body"))
    declared = int(match.group("count"))
    if declared != len(values):
        raise ValueError(
            f"internalField count mismatch for {path.name}: declared {declared}, parsed {len(values)}",
        )
    return FieldData(
        name=path.name,
        path=path,
        kind=_field_kind_from_list(values),
        values=values,
        declared_count=declared,
        uniform=False,
    )


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
    lowered = kind.lower()
    # vector, (symm/spherical)tensor are all written as parenthesized component
    # tuples; only plain scalar lists are bare numbers.
    if "vector" in lowered or "tensor" in lowered:
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
