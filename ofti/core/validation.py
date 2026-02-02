from collections.abc import Callable


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
    text = value.strip().rstrip(";")
    if "[" in text and "]" in text:
        inner = text[text.find("[") + 1 : text.rfind("]")]
    else:
        return "Dimensions must be in brackets, e.g. [0 1 -2 0 0 0 0]."
    parts = [p for p in inner.replace(",", " ").split() if p]
    if len(parts) != 7:
        return "Dimensions must contain exactly 7 integers."
    for part in parts:
        try:
            int(part)
        except ValueError:
            return "Dimensions entries must be integers."
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
    dims, rest = text.split("]", 1)
    dims = dims + "]"
    dims_err = dimension_set_values(dims)
    if dims_err:
        return dims_err
    if not rest.strip():
        return "Dimensioned value missing numeric value."
    return None


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
