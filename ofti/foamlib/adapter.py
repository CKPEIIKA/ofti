from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from ofti.foamlib import fallback


class FoamlibUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("foamlib is not available")


FoamCase: Any = None
FoamFile: Any = None
FoamFieldFile: Any = None

try:  # pragma: no cover - exercised in tests when installed
    from foamlib import FoamCase, FoamFieldFile, FoamFile
    FOAMLIB_AVAILABLE = True
except Exception:  # pragma: no cover - optional fallback
    FOAMLIB_AVAILABLE = False

FoamDictAssignment: Any = None
FoamDictInstruction: Any = None
foamlib_system: Any = None

try:  # pragma: no cover - optional preprocessing extras
    from foamlib.preprocessing import system as foamlib_system
    from foamlib.preprocessing.of_dict import FoamDictAssignment, FoamDictInstruction
    FOAMLIB_PREPROCESSING = True
    FOAMLIB_SYSTEM = True
except Exception:  # pragma: no cover - optional fallback
    FOAMLIB_PREPROCESSING = False
    FOAMLIB_SYSTEM = False

FoamlibDimensionSet: Any = None
FoamlibDimensioned: Any = None
FoamlibField: Any = None

try:  # pragma: no cover - optional richer type helpers
    from foamlib.typing import Dimensioned as FoamlibDimensioned
    from foamlib.typing import DimensionSet as FoamlibDimensionSet
    from foamlib.typing import Field as FoamlibField
except Exception:  # pragma: no cover - foamlib missing or changed
    pass


def available() -> bool:
    return FOAMLIB_AVAILABLE or fallback.available()


def clone_case_directory(source: Path, destination: Path) -> Path | None:
    if not FOAMLIB_AVAILABLE:
        return None
    try:
        from foamlib import FoamCase

        cloned = FoamCase(source).clone(destination)
    except Exception:
        return None
    return Path(getattr(cloned, "path", destination)).expanduser().resolve()


def validate_dimension_set(values: list[float]) -> bool:
    if FoamlibDimensionSet is None:
        return True
    try:
        FoamlibDimensionSet(*values)
    except Exception:
        return False
    return True


def validate_dimensioned_value(payload: float | list[float], dimensions: list[float]) -> bool:
    if FoamlibDimensioned is None:
        return True
    try:
        FoamlibDimensioned(payload, dimensions)
    except Exception:
        return False
    return True


def node_type_label(node: object) -> str | None:
    numeric = _numeric_list_label(node)
    if numeric is not None:
        return numeric
    for predicate, label in _node_label_predicates():
        if predicate(node):
            if label == "array":
                return f"array {getattr(node, 'shape', '')}"
            return label
    if isinstance(node, (list, tuple)):
        return f"list ({len(node)})"
    return type(node).__name__


def node_type_details(node: object) -> list[str]:
    label = node_type_label(node)
    details: list[str] = []
    if label:
        details.append(f"foamlib type: {label}")
    details.append(f"python type: {type(node).__module__}.{type(node).__name__}")
    details.extend(_array_node_details(node))
    details.extend(_dimension_node_details(node))
    details.extend(_mapping_node_details(node))
    return details


def _array_node_details(node: object) -> list[str]:
    details: list[str] = []
    shape = getattr(node, "shape", None)
    if shape is not None:
        details.append(f"shape: {shape}")
    dtype = getattr(node, "dtype", None)
    if dtype is not None:
        details.append(f"dtype: {dtype}")
    return details


def _dimension_node_details(node: object) -> list[str]:
    details: list[str] = []
    if _is_dimension_set(node):
        as_dict = getattr(node, "_asdict", None)
        if callable(as_dict):
            non_zero = {key: value for key, value in as_dict().items() if value}
            details.append(f"dimensions: {non_zero or 'dimensionless'}")
    if _is_dimensioned(node):
        dimensions = getattr(node, "dimensions", None)
        value = getattr(node, "value", None)
        if dimensions is not None:
            details.append(f"dimensions: {dimensions}")
        if value is not None:
            details.append(f"value type: {type(value).__name__}")
    return details


def _mapping_node_details(node: object) -> list[str]:
    if not hasattr(node, "keys"):
        return []
    try:
        keys = [str(key) for key in cast("Any", node) if isinstance(key, str)]
    except Exception:
        keys = []
    if keys:
        return [f"subkeys: {', '.join(keys[:8])}"]
    return []


def _node_label_predicates() -> list[tuple[Callable[[object], bool], str]]:
    return [
        (lambda node: hasattr(node, "keys"), "dict"),
        (_is_dimension_set, "dimensions"),
        (_is_dimensioned, "dimensioned"),
        (_is_foamlib_field, "field"),
        (lambda node: isinstance(node, bool), "bool"),
        (lambda node: isinstance(node, int), "int"),
        (lambda node: isinstance(node, float), "float"),
        (lambda node: isinstance(node, str), "word"),
        (lambda node: hasattr(node, "shape"), "array"),
    ]


def _is_dimension_set(node: object) -> bool:
    return FoamlibDimensionSet is not None and isinstance(node, FoamlibDimensionSet)


def _is_dimensioned(node: object) -> bool:
    return FoamlibDimensioned is not None and isinstance(node, FoamlibDimensioned)


def _is_foamlib_field(node: object) -> bool:
    if FoamlibField is None:
        return False
    try:
        return isinstance(node, cast("type[Any]", FoamlibField))
    except TypeError:
        return False


def _numeric_list_label(values: object) -> str | None:
    raw_values = values
    if isinstance(values, str):
        parsed = _numeric_string_values(values)
        if parsed is not None:
            raw_values = parsed
    shape = getattr(values, "shape", None)
    if shape is not None and len(shape) == 1 and shape[0] in {2, 3, 7}:
        tolist = getattr(values, "tolist", None)
        if callable(tolist):
            raw_values = tolist()
    if not isinstance(raw_values, (list, tuple)):
        return None
    return _numeric_sequence_label(cast("list[object] | tuple[object, ...]", raw_values))


def _numeric_sequence_label(raw_values: list[object] | tuple[object, ...]) -> str | None:
    if not raw_values:
        return None
    floats: list[float] = []
    for item in raw_values:
        if isinstance(item, bool):
            return None
        if not isinstance(item, (int, float)):
            return None
        floats.append(float(item))
    if len(raw_values) in (2, 3):
        return "vector"
    if len(raw_values) == 7 and all(float(value).is_integer() for value in floats):
        return "dimensions"
    return None


def _numeric_string_values(value: str) -> list[float] | None:
    text = value.strip().rstrip(";").strip()
    if text.startswith("uniform"):
        text = text[len("uniform") :].strip()
    if not (text.startswith("(") and text.endswith(")")):
        return None
    parts = text[1:-1].split()
    if not parts:
        return None
    try:
        return [float(part) for part in parts]
    except ValueError:
        return None


def is_foam_file(path: Path) -> bool:
    try:
        head = path.read_text(errors="ignore")[:2048]
    except OSError:
        return False
    return "FoamFile" in head


def is_field_file(path: Path) -> bool:
    if not is_foam_file(path):
        return False
    try:
        head = path.read_text(errors="ignore")[:4096]
    except OSError:
        return False
    return "internalField" in head or "boundaryField" in head


def _split_key(key: str) -> tuple[str, ...]:
    return tuple(part for part in key.split(".") if part)


def _foam_file(path: Path) -> Any:
    if not FOAMLIB_AVAILABLE:
        raise FoamlibUnavailableError
    case_file = _case_relative_foam_file(path)
    if case_file is not None:
        return case_file
    if FoamFile is None:
        raise FoamlibUnavailableError
    return FoamFile(path)


def _case_relative_foam_file(path: Path) -> Any | None:
    if FoamCase is None:
        return None
    resolved = path.expanduser().resolve()
    case_path = _case_root_for_file(resolved)
    if case_path is None:
        return None
    try:
        rel_path = resolved.relative_to(case_path)
        return FoamCase(case_path).file(rel_path)
    except Exception:
        return None


def _case_root_for_file(path: Path) -> Path | None:
    for parent in path.parents:
        if (parent / "system").is_dir() and (
            (parent / "constant").is_dir()
            or (parent / "0").is_dir()
            or (parent / "0.orig").is_dir()
        ):
            return parent
    return None


def _foam_field_file(path: Path) -> Any:
    if not FOAMLIB_AVAILABLE or FoamFieldFile is None:
        raise FoamlibUnavailableError
    return FoamFieldFile(path)


def list_keywords(file_path: Path) -> list[str]:
    if not FOAMLIB_AVAILABLE:
        return fallback.list_keywords(file_path)
    foam_file = _foam_file(file_path)
    return [key for key in foam_file if isinstance(key, str)]


def list_subkeys(file_path: Path, entry: str) -> list[str]:
    if not FOAMLIB_AVAILABLE:
        return fallback.list_subkeys(file_path, entry)
    foam_file = _foam_file(file_path)
    key_parts = _split_key(entry)
    node = foam_file.getone(key_parts or None)
    if node is None:
        return []
    if hasattr(node, "keys"):
        return [key for key in node if isinstance(key, str)]
    return []


def read_entry(file_path: Path, key: str) -> str:
    if not FOAMLIB_AVAILABLE:
        return fallback.read_entry(file_path, key)
    foam_file = _foam_file(file_path)
    key_parts = _split_key(key)
    node = foam_file.getone(key_parts or None)
    if node is None:
        raise KeyError(key)
    key_name = key_parts[-1] if key_parts else ""
    return _dump_entry_value(key_name, node)


def read_entry_node(file_path: Path, key: str) -> object:
    if not FOAMLIB_AVAILABLE:
        return fallback.read_entry_node(file_path, key)
    foam_file = _foam_file(file_path)
    key_parts = _split_key(key)
    node = foam_file.getone(key_parts or None)
    if node is None:
        raise KeyError(key)
    return node


def read_file_dict(file_path: Path, *, include_header: bool = True) -> dict[str, object]:
    if not FOAMLIB_AVAILABLE:
        return fallback.parse_mapping(file_path)
    try:
        foam_file = _foam_file(file_path)
    except FoamlibUnavailableError:
        return fallback.parse_mapping(file_path)
    as_dict = getattr(foam_file, "as_dict", None)
    if not callable(as_dict):
        return fallback.parse_mapping(file_path)
    raw = as_dict(include_header=include_header)
    if not isinstance(raw, dict):
        return fallback.parse_mapping(file_path)
    return {str(key): _snapshot_value(value) for key, value in raw.items() if key is not None}


def _snapshot_value(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _snapshot_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_snapshot_value(item) for item in value]
    converted = _snapshot_converted(value, "tolist")
    if converted is not None:
        return converted
    converted = _snapshot_converted(value, "_asdict")
    if converted is not None:
        return converted
    return str(value)


def _snapshot_converted(value: object, method_name: str) -> object | None:
    converter = getattr(value, method_name, None)
    if not callable(converter):
        return None
    try:
        return _snapshot_value(converter())
    except Exception:
        return None


def read_field_entry(file_path: Path, key: str) -> str:
    if not FOAMLIB_AVAILABLE:
        return fallback.read_field_entry(file_path, key)
    key_parts = _split_key(key)
    try:
        field_file = _foam_field_file(file_path)
        node = field_file.getone(key_parts or None)
    except FoamlibUnavailableError:
        return fallback.read_field_entry(file_path, key)
    if node is None:
        raise KeyError(key)
    if _empty_foamlib_field_node(node):
        return fallback.read_field_entry(file_path, key)
    key_name = key_parts[-1] if key_parts else ""
    return _dump_entry_value(key_name, node)


def read_field_entry_node(file_path: Path, key: str) -> object:
    if not FOAMLIB_AVAILABLE:
        return fallback.read_field_entry_node(file_path, key)
    key_parts = _split_key(key)
    try:
        field_file = _foam_field_file(file_path)
        node = field_file.getone(key_parts or None)
    except FoamlibUnavailableError:
        return fallback.read_field_entry_node(file_path, key)
    if node is None:
        raise KeyError(key)
    if _empty_foamlib_field_node(node):
        return fallback.read_field_entry_node(file_path, key)
    return node


def _empty_foamlib_field_node(node: object) -> bool:
    shape = getattr(node, "shape", None)
    if shape is not None:
        return tuple(shape) == (0,)
    if isinstance(node, (list, tuple)):
        return len(node) == 0
    return False


def _foamlib_can_write(value: str) -> bool:
    value = value.strip()
    if not value:
        return True
    if value.startswith("{"):
        return False
    if value.startswith("uniform"):
        return False
    if any(ch in value for ch in "(){}"):  # arrays/vectors/dicts
        return False
    return len(value.split()) == 1


def _parse_uniform_value(value: str) -> object | None:
    text = value.strip()
    if text.startswith("uniform"):
        text = text[len("uniform") :].strip()
    if text.startswith("(") and text.endswith(")"):
        inner = text[1:-1].strip()
        if not inner:
            return None
        parts = inner.split()
        try:
            return [float(part) for part in parts]
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def write_entry(file_path: Path, key: str, value: str) -> bool:
    if not FOAMLIB_AVAILABLE:
        return fallback.write_entry(file_path, key, value)
    if FOAMLIB_PREPROCESSING:
        ok = _write_entry_with_assignment(file_path, key, value, case_path=None)
        if ok:
            return True
    foam_file = _foam_file(file_path)
    key_parts = _split_key(key)
    cleaned = value.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    parsed = _parse_uniform_value(cleaned)
    if parsed is not None:
        with foam_file:
            foam_file[key_parts or None] = parsed
        return True
    if not _foamlib_can_write(cleaned):
        return False
    with foam_file:
        foam_file[key_parts or None] = cleaned
    return True


def write_field_entry(file_path: Path, key: str, value: str) -> bool:
    if not FOAMLIB_AVAILABLE:
        return fallback.write_field_entry(file_path, key, value)
    field_file = _foam_field_file(file_path)
    key_parts = _split_key(key)
    parsed = _parse_field_entry_payload(key_parts, value)
    if parsed is None:
        return False
    with field_file:
        field_file[key_parts or None] = parsed
    return True


def _parse_field_entry_payload(key_parts: tuple[str, ...], value: str) -> object | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    key_name = key_parts[-1] if key_parts else ""
    payload = _field_entry_payload_text(key_name, cleaned)
    try:
        loaded = FoamFieldFile.loads(payload, include_header=False)
    except Exception:
        return None
    getter = getattr(loaded, "get", None)
    if not callable(getter):
        return None
    return getter(key_name)


def _field_entry_payload_text(key_name: str, cleaned: str) -> str:
    if cleaned.startswith("{"):
        return f"{key_name}\n{cleaned}\n"
    if not cleaned.endswith(";"):
        cleaned = f"{cleaned};"
    return f"{key_name} {cleaned}"


def apply_assignment(
    case_path: Path,
    file_path: Path,
    key_path: list[str],
    value: str,
) -> bool:
    if not FOAMLIB_PREPROCESSING:
        return False
    key = ".".join(key_path)
    return _write_entry_with_assignment(file_path, key, value, case_path=case_path)


def _write_entry_with_assignment(
    file_path: Path,
    key: str,
    value: str,
    *,
    case_path: Path | None,
) -> bool:
    if not FOAMLIB_PREPROCESSING or FoamDictAssignment is None or FoamDictInstruction is None:
        return False
    cleaned = value.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    parsed = _parse_uniform_value(cleaned)
    payload: object
    if parsed is not None:
        payload = parsed
    else:
        if not _foamlib_can_write(cleaned):
            return False
        payload = cleaned
    try:
        instruction = _instruction_for_file(
            file_path,
            list(_split_key(key)),
            case_path=case_path,
        )
        assignment = FoamDictAssignment(instruction=instruction, value=payload)
        assignment.set_value()
    except Exception:
        return False
    return True


def _instruction_for_file(
    file_path: Path,
    keys: list[str],
    *,
    case_path: Path | None,
) -> Any:
    rel_path: Path
    if case_path is not None:
        try:
            rel_path = file_path.relative_to(case_path)
        except ValueError:
            rel_path = file_path
    else:
        rel_path = file_path
    helper = _system_helper_for(rel_path)
    if helper is not None:
        return helper(keys)
    return FoamDictInstruction(file_name=rel_path, keys=keys)


def _system_helper_for(rel_path: Path) -> Any | None:
    if not FOAMLIB_SYSTEM or foamlib_system is None:
        return None
    normalized = rel_path.as_posix()
    mapping = {
        "system/controlDict": foamlib_system.control_dict,
        "system/fvSchemes": foamlib_system.fv_schemes,
        "system/fvSolution": foamlib_system.fv_solution,
        "system/simulationParameters": foamlib_system.simulation_parameters,
    }
    return mapping.get(normalized)


def _dump_entry_value(key_name: str, node: object) -> str:
    payload = cast("Any", {key_name: node})
    text = FoamFile.dumps(payload, ensure_header=False).decode().strip()
    lines = text.splitlines()
    if len(lines) == 1 and key_name:
        line = lines[0].strip()
        parts = line.split(None, 1)
        if parts and parts[0] == key_name and len(parts) == 2:
            return parts[1].strip()
    return text


def parse_boundary_file(path: Path) -> tuple[list[str], dict[str, str]]:
    if not FOAMLIB_AVAILABLE:
        return fallback.parse_boundary_file(path)
    foam_file = _foam_file(path)
    entries = foam_file.getone(None)
    patches: list[str] = []
    patch_types: dict[str, str] = {}
    if not isinstance(entries, list):
        return patches, patch_types
    for item in entries:
        row = _boundary_entry_row(item)
        if row is None:
            continue
        name, entry_type = row
        patches.append(name)
        if entry_type is not None:
            patch_types[name] = entry_type
    return patches, patch_types


def _boundary_entry_row(item: object) -> tuple[str, str | None] | None:
    if not isinstance(item, tuple) or len(item) != 2:
        return None
    name, data = item
    if not isinstance(name, str):
        return None
    if not isinstance(data, Mapping):
        return name, None
    entry_type = cast("Mapping[str, object]", data).get("type")
    return name, entry_type if isinstance(entry_type, str) else None


def rename_boundary_patch(path: Path, old: str, new: str) -> bool:
    if not FOAMLIB_AVAILABLE:
        return fallback.rename_boundary_patch(path, old, new)
    foam_file = _foam_file(path)
    entries = foam_file.getone(None)
    if not isinstance(entries, list):
        return False
    updated: list[tuple[object, object]] = []
    found = False
    for item in entries:
        if not isinstance(item, tuple) or len(item) != 2:
            updated.append(item)
            continue
        name, data = item
        if name == old:
            updated.append((new, data))
            found = True
        else:
            updated.append(item)
    if not found:
        return False
    with foam_file:
        foam_file[None] = updated
    return True


def change_boundary_patch_type(path: Path, patch: str, new_type: str) -> bool:
    if not FOAMLIB_AVAILABLE:
        return fallback.change_boundary_patch_type(path, patch, new_type)
    foam_file = _foam_file(path)
    entries = foam_file.getone(None)
    if not isinstance(entries, list):
        return False
    updated: list[tuple[object, object]] = []
    found = False
    for item in entries:
        if not isinstance(item, tuple) or len(item) != 2:
            updated.append(item)
            continue
        name, data = item
        if name == patch and isinstance(data, dict):
            data = dict(data)
            data["type"] = new_type
            updated.append((name, data))
            found = True
        else:
            updated.append(item)
    if not found:
        return False
    with foam_file:
        foam_file[None] = updated
    return True


def rename_boundary_field_patch(file_path: Path, old: str, new: str) -> bool:
    if not FOAMLIB_AVAILABLE:
        return fallback.rename_boundary_field_patch(file_path, old, new)
    field_file = _foam_field_file(file_path)
    key_old = ("boundaryField", old)
    key_new = ("boundaryField", new)
    try:
        value = field_file.getone(key_old)
    except Exception:
        value = None
    if value is None:
        return False
    with field_file:
        field_file[key_new] = value
        try:
            del field_file[key_old]
        except Exception:
            return False
    return True
