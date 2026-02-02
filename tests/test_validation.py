"""Validation helpers should accept common OpenFOAM value formats."""

from ofti.core import validation


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


def test_dimension_set_validation_and_normalization() -> None:
    """Validate dimension sets and normalize spacing."""
    assert validation.dimension_set_values("[0 1 -2 0 0 0 0]") is None
    assert validation.dimension_set_values("[0 1 -2 0 0 0]") is not None
    normalized = validation.normalize_dimension_set("[0, 1, -2, 0, 0, 0, 0];")
    assert normalized == "[0 1 -2 0 0 0 0]"


def test_dimensioned_value_validation_and_normalization() -> None:
    """Validate dimensioned values and normalize output."""
    assert validation.dimensioned_value("[0 1 -2 0 0 0 0] 1e-05") is None
    assert validation.dimensioned_value("[0 1 -2 0 0 0 0] (1 2 3)") is None
    assert validation.dimensioned_value("[0 1 -2 0 0 0 0]") is not None
    normalized = validation.normalize_dimensioned_value("[0 1 -2 0 0 0 0] 1e-05;")
    assert normalized == "[0 1 -2 0 0 0 0] 1e-05"
    normalized_vec = validation.normalize_dimensioned_value("[0 1 -2 0 0 0 0] (1 2 3)")
    assert normalized_vec == "[0 1 -2 0 0 0 0] (1 2 3)"


def test_normalize_value_for_type() -> None:
    """Normalize by type label when possible."""
    assert (
        validation.normalize_value_for_type("dimensions", "[0 1 -2 0 0 0 0];")
        == "[0 1 -2 0 0 0 0]"
    )
    assert (
        validation.normalize_value_for_type("dimensioned", "[0 0 0 0 0 0 0] 10;")
        == "[0 0 0 0 0 0 0] 10"
    )
    assert validation.normalize_value_for_type("word", "alpha") is None


def test_normalize_field_value_uniform() -> None:
    assert validation.normalize_field_value("uniform 1;") == "uniform 1"
    assert validation.normalize_field_value("uniform (1 2 3);") == "uniform (1 2 3)"
    assert validation.normalize_field_value("uniform (1.0 2.0 3.0)") == "uniform (1 2 3)"
    assert validation.normalize_field_value("nonuniform List<scalar>") is None
