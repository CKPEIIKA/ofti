from ofti.core.entry_meta import choose_validator
from ofti.core.validation import (
    as_float,
    as_int,
    dimensioned_value,
    field_value,
    vector_values,
)


def test_choose_validator_treats_real_vector_as_vector() -> None:
    validator, label = choose_validator("U", "(1 2 3)")
    assert validator is vector_values
    assert label == "vector"


def test_choose_validator_does_not_treat_scheme_as_vector() -> None:
    value = "div(tauMC) Gauss linear"
    validator, label = choose_validator("divScheme", value)
    # Should fall back to generic text validator, not vector_values.
    assert validator is not vector_values
    assert label == "text"


def test_choose_validator_uses_float_for_scalar_with_decimal() -> None:
    value = "preMij          0.014;"
    validator, label = choose_validator("preMij", value)
    assert validator is as_float
    assert label == "float"


def test_choose_validator_uses_int_for_scalar_integer() -> None:
    value = "5;"
    validator, label = choose_validator("startFrom", value)
    assert validator is as_int
    assert label == "integer"


def test_choose_validator_labels_word_tokens() -> None:
    value = "Gauss;"
    _validator, label = choose_validator("divScheme", value)
    assert label == "word"


def test_choose_validator_detects_internal_field() -> None:
    validator, label = choose_validator("internalField", "uniform 0")
    assert validator is field_value
    assert label == "field"


def test_choose_validator_detects_boundary_field_value() -> None:
    validator, label = choose_validator("boundaryField.inlet.value", "uniform (1 0 0)")
    assert validator is field_value
    assert label == "field"


def test_choose_validator_detects_dimensioned_value() -> None:
    validator, label = choose_validator("nu", "[0 2 -1 0 0 0 0] 1e-05")
    assert validator is dimensioned_value
    assert label == "dimensioned"
