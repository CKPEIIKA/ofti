from collections.abc import Callable

try:  # pragma: no cover - optional foamlib typing helpers
    from foamlib.typing import Dimensioned as FoamlibDimensioned
    from foamlib.typing import DimensionSet as FoamlibDimensionSet
except Exception:  # pragma: no cover - foamlib missing or changed
    FoamlibDimensioned = None  # type: ignore[assignment]
    FoamlibDimensionSet = None  # type: ignore[assignment]


def non_empty(value: str) -> str | None:
    if not value.strip():
        return "Value must not be empty."
    return None


def _normalize_numeric(value: str) -> str:
    """
    Normalize a numeric value by trimming whitespace and an optional
    trailing semicolon, as commonly used in OpenFOAM dictionaries.
    """
    text = value.strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    return text


def as_int(value: str) -> str | None:
    text = _normalize_numeric(value)
    try:
        int(text)
    except ValueError:
        return "Value must be an integer."
    return None


def as_float(value: str) -> str | None:
    text = _normalize_numeric(value)
    try:
        float(text)
    except ValueError:
        return "Value must be a number."
    return None


def bool_flag(value: str) -> str | None:
    if value not in ("on", "off", "true", "false", "True", "False"):
        return "Value should be a boolean-like flag (on/off, true/false)."
    return None


def vector_values(value: str) -> str | None:
    """
    Validate a simple OpenFOAM-style vector, e.g.:
      (1 2 3) or 'uniform (1 2 3)'
    """
    text = value.strip()
    if text.lower().startswith("uniform"):
        text = text.split(None, 1)[1] if " " in text else ""
    # Extract between parentheses if present.
    if "(" in text and ")" in text:
        text = text[text.find("(") + 1 : text.rfind(")")]
    parts = [p for p in text.replace(",", " ").split() if p]
    if not parts:
        return "Vector must contain at least one numeric value."
    try:
        for p in parts:
            float(p)
    except ValueError:
        return "Vector entries must be numeric."
    return None


def dimension_set_values(value: str) -> str | None:
    """
    Validate OpenFOAM dimensions entry: seven integers in brackets.
    Example: [0 1 -2 0 0 0 0]
    """
    parsed = _parse_dimension_set(value)
    if parsed is None:
        return "Dimensions must be in brackets, e.g. [0 1 -2 0 0 0 0]."
    if len(parsed) != 7:
        return "Dimensions must contain exactly 7 integers."
    for part in parsed:
        if not float(part).is_integer():
            return "Dimensions entries must be integers."
    if FoamlibDimensionSet is not None:
        try:
            FoamlibDimensionSet(*parsed)
        except Exception:
            return "Dimensions entries must be valid numbers."
    return None


def dimensioned_value(value: str) -> str | None:
    """
    Validate dimensioned scalar/vector entries:
      [0 2 -2 0 0 0 0] 1e-05
    """
    text = value.strip().rstrip(";")
    if not text.startswith("["):
        return "Dimensioned value must start with dimensions, e.g. [0 1 -2 0 0 0 0] 1e-05."
    if "]" not in text:
        return "Dimensioned value missing closing bracket."
    dims_text, rest = text.split("]", 1)
    dims_text = dims_text + "]"
    dims_err = dimension_set_values(dims_text)
    if dims_err:
        return dims_err
    if not rest.strip():
        return "Dimensioned value missing numeric value."
    parsed = _parse_dimensioned_value(text)
    if parsed is None:
        return "Dimensioned value should be numeric or vector-like."
    dims, payload, _normalized = parsed
    if FoamlibDimensioned is not None:
        try:
            FoamlibDimensioned(payload, dims)
        except Exception:
            return "Dimensioned value has invalid numeric/vector data."
    return None


def normalize_dimension_set(value: str) -> str | None:
    parsed = _parse_dimension_set(value)
    if parsed is None or len(parsed) != 7:
        return None
    normalized = [str(int(val)) if float(val).is_integer() else str(val) for val in parsed]
    return f"[{' '.join(normalized)}]"


def normalize_dimensioned_value(value: str) -> str | None:
    parsed = _parse_dimensioned_value(value)
    if parsed is None:
        return None
    dims, payload, _ = parsed
    dims_text = normalize_dimension_set(f"[{' '.join(str(v) for v in dims)}]")
    if dims_text is None:
        return None
    if isinstance(payload, (list, tuple)):
        inner = " ".join(_format_number(val) for val in payload)
        value_text = f"({inner})"
    else:
        value_text = _format_number(payload)
    return f"{dims_text} {value_text}"


def normalize_value_for_type(type_label: str, value: str) -> str | None:
    if type_label == "dimensions":
        return normalize_dimension_set(value)
    if type_label == "dimensioned":
        return normalize_dimensioned_value(value)
    if type_label == "field":
        return normalize_field_value(value)
    return None


def _format_number(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _parse_dimension_set(value: str) -> list[float] | None:
    text = value.strip().rstrip(";")
    if "[" not in text or "]" not in text:
        return None
    inner = text[text.find("[") + 1 : text.rfind("]")]
    parts = [p for p in inner.replace(",", " ").split() if p]
    if not parts:
        return None
    parsed: list[float] = []
    for part in parts:
        try:
            parsed.append(float(part))
        except ValueError:
            return None
    return parsed


def _parse_vector_payload(text: str) -> list[float] | None:
    if "(" not in text or ")" not in text:
        return None
    inner = text[text.find("(") + 1 : text.rfind(")")]
    parts = [p for p in inner.replace(",", " ").split() if p]
    if not parts:
        return None
    values: list[float] = []
    for part in parts:
        try:
            values.append(float(part))
        except ValueError:
            return None
    return values


def _parse_dimensioned_value(value: str) -> tuple[list[float], object, str] | None:
    text = value.strip().rstrip(";")
    if "]" not in text:
        return None
    dims_text, rest = text.split("]", 1)
    dims = _parse_dimension_set(dims_text + "]")
    if dims is None:
        return None
    rest = rest.strip()
    if rest.lower().startswith("uniform"):
        rest = rest.split(None, 1)[1] if " " in rest else ""
        rest = rest.strip()
    if not rest:
        return None
    vector = _parse_vector_payload(rest)
    if vector is not None:
        return dims, vector, rest
    try:
        scalar = float(rest)
    except ValueError:
        return None
    return dims, scalar, rest


def normalize_field_value(value: str) -> str | None:
    text = value.strip().rstrip(";")
    if not text:
        return None
    lower = text.lower()
    if not lower.startswith("uniform"):
        return None
    parts = text.split(None, 1)
    if len(parts) < 2:
        return None
    payload = parts[1].strip()
    if not payload:
        return None
    vector = _parse_vector_payload(payload)
    if vector is not None:
        inner = " ".join(_format_number(val) for val in vector)
        return f"uniform ({inner})"
    try:
        scalar = float(payload)
    except ValueError:
        return None
    return f"uniform {_format_number(scalar)}"


def field_value(value: str) -> str | None:
    """
    Validate OpenFOAM field values such as:
      uniform 0
      uniform (1 0 0)
      nonuniform List<scalar> ...
    """
    text = value.strip().rstrip(";")
    if not text:
        return "Value must not be empty."
    lower = text.lower()
    if lower.startswith("uniform"):
        parts = text.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            return "Uniform field requires a value."
        return None
    if lower.startswith("nonuniform"):
        if "list" in lower or "(" in text or "{" in text:
            return None
        return "Nonuniform field should include list data."
    return "Field value should start with 'uniform' or 'nonuniform'."


Validator = Callable[[str], str | None]
