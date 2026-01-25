from __future__ import annotations

from pathlib import Path

from ofti.core.validation import Validator, as_float, as_int, bool_flag, non_empty, vector_values
from ofti.foam.openfoam import (
    OpenFOAMError,
    get_entry_comments,
    get_entry_enum_values,
    get_entry_info,
    is_scalar_value,
    list_subkeys,
    looks_like_dict,
    normalize_scalar_token,
    read_entry,
)


def get_entry_metadata(
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    file_path: Path,
    full_key: str,
) -> tuple[str, str, list[str], list[str], list[str], Validator]:
    """
    Load entry metadata (value, type label, subkeys, comments, info_lines, validator),
    using a simple cache to avoid repeated foamDictionary calls while
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
    subkeys = list_subkeys(file_path, full_key)
    comments = get_entry_comments(file_path, full_key)
    info_lines = get_entry_info(file_path, full_key)
    info_lines.extend(boundary_condition_info(file_path, full_key))
    if subkeys or looks_like_dict(value):
        validator = non_empty
        type_label = "dict"

    # If foamDictionary reports an explicit list of allowed values via
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
    subkeys = list_subkeys(file_path, full_key)
    comments = get_entry_comments(file_path, full_key)
    info_lines = get_entry_info(file_path, full_key)
    info_lines.extend(boundary_condition_info(file_path, full_key))
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

    # Prefer vector validation when the value looks like a vector.
    # Only treat as vector if it actually parses as a vector; otherwise
    # fall back to scalar / key-based heuristics (e.g. schemes like
    # "div(tauMC) Gauss linear" are not vectors even though they have
    # parentheses in the name).
    if "(" in value and ")" in value:
        vec_error = vector_values(value)
        if vec_error is None:
            return vector_values, "vector"

    # Try to infer scalar type from the value itself: check the last token
    # for a numeric literal before falling back to key-based heuristics.
    scalar_choice = _infer_scalar_choice(value)
    if scalar_choice is not None:
        return scalar_choice

    numeric_choice = _infer_numeric_choice(value)
    if numeric_choice is not None:
        return numeric_choice

    validator = _guess_validator(key)
    # Simple label based on which validator was chosen.
    if validator is bool_flag:
        label = "boolean-like"
    elif validator is as_int:
        label = "integer"
    elif validator is as_float:
        label = "float"
    else:
        label = "text"
    return validator, label


def _read_optional_entry(file_path: Path, key: str) -> str | None:
    try:
        return read_entry(file_path, key).strip()
    except OpenFOAMError:
        return None


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
