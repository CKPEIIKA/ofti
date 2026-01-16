"""Validation helpers should accept common OpenFOAM value formats."""

from of_tui import validation


def test_non_empty_validator() -> None:
    """Reject empty values."""
    assert validation.non_empty("abc") is None
    assert validation.non_empty("   ") is not None


def test_as_int_validator() -> None:
    """Accept integer-like values with optional semicolons."""
    assert validation.as_int("10") is None
    assert validation.as_int("10;") is None
    assert validation.as_int("10.5") is not None


def test_as_float_validator() -> None:
    """Accept float-like values with optional semicolons."""
    assert validation.as_float("10") is None
    assert validation.as_float("10;") is None
    assert validation.as_float("10.5") is None
    assert validation.as_float("10.5;") is None
    assert validation.as_float("abc") is not None


def test_bool_flag_validator() -> None:
    """Allow common boolean flags and reject others."""
    assert validation.bool_flag("on") is None
    assert validation.bool_flag("false") is None
    assert validation.bool_flag("maybe") is not None


def test_vector_values_validator_plain_and_uniform() -> None:
    """Accept common vector formats and reject invalid values."""
    assert validation.vector_values("(1 2 3)") is None
    assert validation.vector_values("uniform (1.0 2.0 3.0)") is None
    assert validation.vector_values("()") is not None
    assert validation.vector_values("(1 a 3)") is not None
