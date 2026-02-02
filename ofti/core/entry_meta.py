from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ofti.core.entry_io import list_subkeys, read_entry
from ofti.core.validation import (
    Validator,
    as_float,
    as_int,
    bool_flag,
    dimension_set_values,
    dimensioned_value,
    field_value,
    non_empty,
    vector_values,
)
from ofti.foam.openfoam import (
    OpenFOAMError,
    get_entry_comments,
    get_entry_enum_values,
    get_entry_info,
    is_scalar_value,
    looks_like_dict,
    normalize_scalar_token,
)
from ofti.foamlib import adapter as foamlib_integration


def get_entry_metadata(
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    file_path: Path,
    full_key: str,
) -> tuple[str, str, list[str], list[str], list[str], Validator]:
    """
    Load entry metadata (value, type label, subkeys, comments, info_lines, validator),
    using a simple cache to avoid repeated foamlib calls while
    navigating.
    """
    if full_key in cache:
        value, type_label, subkeys, comments, info_lines = cache[full_key]
        validator, _ = choose_validator(full_key, value)
        return value, type_label, subkeys, comments, info_lines, validator

    try:
        value = read_entry(file_path, full_key)
    except OpenFOAMError:
        value = "<error reading value>"

    validator, type_label = choose_validator(full_key, value)
    validator, type_label = detect_type_with_foamlib(
        file_path,
        full_key,
        validator,
        type_label,
    )
    subkeys = list_subkeys(file_path, full_key)
    comments = get_entry_comments(file_path, full_key)
    info_lines = get_entry_info(file_path, full_key)
    info_lines.extend(boundary_condition_info(file_path, full_key))
    # Type is already shown in the entry preview; avoid repeating it in hints.
    if subkeys or looks_like_dict(value):
        validator = non_empty
        type_label = "dict"

    # If foamlib reports an explicit list of allowed values via
    # `-list`, prefer an enum-style validator over heuristics.
    enum_values = get_entry_enum_values(file_path, full_key)
    if enum_values:
        allowed_set = set(enum_values)

        def enum_validator(v: str) -> str | None:
            text = v.strip().rstrip(";").strip()
            if text in allowed_set:
                return None
            return f"Value must be one of: {', '.join(sorted(allowed_set))}."

        validator = enum_validator
        type_label = "enum"
        # Surface allowed values in the info pane as well.
        info_lines = [*info_lines, f"Allowed values: {', '.join(enum_values)}"]

    cache[full_key] = (value, type_label, subkeys, comments, info_lines)
    return value, type_label, subkeys, comments, info_lines, validator


def refresh_entry_cache(
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    file_path: Path,
    full_key: str,
) -> None:
    """
    Refresh a single entry in the cache after an edit, swallowing
    OpenFOAM errors so the UI remains responsive.
    """
    try:
        value = read_entry(file_path, full_key)
    except OpenFOAMError:
        return

    _validator, type_label = choose_validator(full_key, value)
    _validator, type_label = detect_type_with_foamlib(
        file_path,
        full_key,
        _validator,
        type_label,
    )
    subkeys = list_subkeys(file_path, full_key)
    comments = get_entry_comments(file_path, full_key)
    info_lines = get_entry_info(file_path, full_key)
    info_lines.extend(boundary_condition_info(file_path, full_key))
    # Type is already shown in the entry preview; avoid repeating it in hints.
    if subkeys or looks_like_dict(value):
        type_label = "dict"
    cache[full_key] = (value, type_label, subkeys, comments, info_lines)


def boundary_condition_info(file_path: Path, full_key: str) -> list[str]:
    """
    Provide extra info for boundary patches: show type/value when possible.
    """
    parts = full_key.split(".")
    info: list[str] = []
    if "boundaryField" not in parts:
        return info
    idx = parts.index("boundaryField")
    if idx + 1 >= len(parts):
        return info
    patch = parts[idx + 1]
    patch_key = ".".join(parts[: idx + 2])

    bc_type = _read_optional_entry(file_path, f"{patch_key}.type")
    if bc_type:
        info.append(f"BC {patch} type: {bc_type}")
    else:
        info.append(f"BC {patch}: missing required entry 'type'")

    bc_value = _read_optional_entry(file_path, f"{patch_key}.value")
    if bc_value:
        info.append(f"BC {patch} value: {bc_value}")
    else:
        info.append(f"BC {patch}: value entry not found")

    return info


def choose_validator(key: str, value: str) -> tuple[Validator, str]:
    """
    Choose a validator based on both key name and current value.

    This allows us to handle scalar types and simple vectors.
    """
    if looks_like_dict(value):
        return non_empty, "dict"

    key_lower = key.lower()
    detectors = (
        _validator_for_dimensions,
        _validator_for_field,
        _validator_for_dimensioned,
        _validator_for_vector,
        _validator_for_scalar,
        _validator_for_numeric,
    )
    for detector in detectors:
        result = detector(key_lower, value)
        if result is not None:
            return result

    validator = _guess_validator(key)
    return validator, _label_for_validator(validator)


def _validator_for_dimensions(key_lower: str, _value: str) -> tuple[Validator, str] | None:
    if key_lower.endswith(("dimensions", "dimension")):
        return dimension_set_values, "dimensions"
    return None


def _validator_for_field(key_lower: str, _value: str) -> tuple[Validator, str] | None:
    if key_lower.endswith("internalfield"):
        return field_value, "field"
    if "boundaryfield" in key_lower and key_lower.endswith("value"):
        return field_value, "field"
    return None


def _validator_for_dimensioned(_key_lower: str, value: str) -> tuple[Validator, str] | None:
    if value.strip().startswith("[") and "]" in value:
        return dimensioned_value, "dimensioned"
    return None


def _validator_for_vector(_key_lower: str, value: str) -> tuple[Validator, str] | None:
    if "(" not in value or ")" not in value:
        return None
    if vector_values(value) is None:
        return vector_values, "vector"
    return None


def _validator_for_scalar(_key_lower: str, value: str) -> tuple[Validator, str] | None:
    return _infer_scalar_choice(value)


def _validator_for_numeric(_key_lower: str, value: str) -> tuple[Validator, str] | None:
    return _infer_numeric_choice(value)


def _label_for_validator(validator: Validator) -> str:
    if validator is bool_flag:
        return "boolean-like"
    if validator is as_int:
        return "integer"
    if validator is as_float:
        return "float"
    return "text"


def _read_optional_entry(file_path: Path, key: str) -> str | None:
    try:
        return read_entry(file_path, key).strip()
    except OpenFOAMError:
        return None


def _foamlib_type_info(file_path: Path, _full_key: str) -> list[str]:
    if not (foamlib_integration.available() and foamlib_integration.is_foam_file(file_path)):
        return []
    return []


try:  # pragma: no cover - optional dependency for richer type labels
    from foamlib.typing import Dimensioned as FoamlibDimensioned
    from foamlib.typing import DimensionSet as FoamlibDimensionSet
    from foamlib.typing import Field as FoamlibField
except Exception:  # pragma: no cover - foamlib missing or changed
    FoamlibDimensionSet = None  # type: ignore[assignment]
    FoamlibDimensioned = None  # type: ignore[assignment]
    FoamlibField = None  # type: ignore[assignment]


def _foamlib_node_label(node: object) -> str | None:
    for predicate, label in _foamlib_label_predicates():
        if predicate(node):
            if label == "array":
                return f"array {getattr(node, 'shape', '')}"
            return label
    if isinstance(node, (list, tuple)):
        numeric = _numeric_list_info(node)
        if numeric == "vector":
            return "vector"
        if numeric == "dimensions":
            return "dimensions"
        return f"list ({len(node)})"
    return type(node).__name__


def _foamlib_label_predicates() -> list[tuple[Callable[[object], bool], str]]:
    predicates: list[tuple[Callable[[object], bool], str]] = [
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
    return predicates


def _is_dimension_set(node: object) -> bool:
    return FoamlibDimensionSet is not None and isinstance(node, FoamlibDimensionSet)


def _is_dimensioned(node: object) -> bool:
    return FoamlibDimensioned is not None and isinstance(node, FoamlibDimensioned)


def _is_foamlib_field(node: object) -> bool:
    if FoamlibField is None:
        return False
    try:
        return isinstance(node, FoamlibField)
    except TypeError:
        return False


def _numeric_list_info(values: object) -> str | None:
    if not isinstance(values, (list, tuple)) or not values:
        return None
    floats: list[float] = []
    for item in values:
        if isinstance(item, bool):
            return None
        if isinstance(item, (int, float)):
            floats.append(float(item))
            continue
        return None
    if len(values) in (2, 3):
        return "vector"
    if len(values) == 7 and all(float(v).is_integer() for v in floats):
        return "dimensions"
    return None


def detect_type_with_foamlib(
    file_path: Path,
    full_key: str,
    validator: Validator,
    type_label: str,
) -> tuple[Validator, str]:
    if not (foamlib_integration.available() and foamlib_integration.is_foam_file(file_path)):
        return validator, type_label
    try:
        if foamlib_integration.is_field_file(file_path):
            node = foamlib_integration.read_field_entry_node(file_path, full_key)
        else:
            node = foamlib_integration.read_entry_node(file_path, full_key)
    except (KeyError, Exception):
        node = None

    label = _foamlib_node_label(node) if node is not None else None
    if not label:
        return validator, type_label
    mapping = {
        "dict": non_empty,
        "bool": bool_flag,
        "int": as_int,
        "float": as_float,
        "word": non_empty,
        "vector": vector_values,
        "dimensions": dimension_set_values,
        "dimensioned": dimensioned_value,
        "field": field_value,
    }
    return mapping.get(label, validator), label


def _guess_validator(key: str) -> Validator:
    """
    Simple heuristic to choose a validator based on key name.
    """
    lower = key.lower()
    if any(tok in lower for tok in ("on", "off", "switch", "enable", "disable")):
        return bool_flag
    if any(tok in lower for tok in ("iter", "step", "count")):
        return as_int
    if any(tok in lower for tok in ("tol", "dt", "time", "coeff", "alpha", "beta")):
        return as_float
    return non_empty


def _is_word_token(token: str) -> bool:
    stripped = token.strip().strip('"')
    if not stripped:
        return False
    if not any(ch.isalpha() for ch in stripped):
        return False
    return all(ch.isalnum() or ch in ("_", "-", ".", "/") for ch in stripped)


def _infer_scalar_choice(value: str) -> tuple[Validator, str] | None:
    if not is_scalar_value(value):
        return None
    token = normalize_scalar_token(value)
    lower = token.lower()
    if lower in {"on", "off", "true", "false", "yes", "no"}:
        return bool_flag, "boolean-like"
    if token and _is_word_token(token):
        return non_empty, "word"
    return None


def _infer_numeric_choice(value: str) -> tuple[Validator, str] | None:
    tokens = value.replace(";", " ").split()
    if not tokens:
        return None
    last = tokens[-1]
    try:
        int(last)
        if "." not in last and "e" not in last.lower():
            return as_int, "integer"
    except ValueError:
        pass
    try:
        float(last)
    except ValueError:
        return None
    return as_float, "float"
