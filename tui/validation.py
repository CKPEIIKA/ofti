from typing import Callable, Optional


def non_empty(value: str) -> Optional[str]:
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


def as_int(value: str) -> Optional[str]:
    text = _normalize_numeric(value)
    try:
        int(text)
    except ValueError:
        return "Value must be an integer."
    return None


def as_float(value: str) -> Optional[str]:
    text = _normalize_numeric(value)
    try:
        float(text)
    except ValueError:
        return "Value must be a number."
    return None


def bool_flag(value: str) -> Optional[str]:
    if value not in ("on", "off", "true", "false", "True", "False"):
        return "Value should be a boolean-like flag (on/off, true/false)."
    return None


def vector_values(value: str) -> Optional[str]:
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


Validator = Callable[[str], Optional[str]]
