from of_tui.app import _choose_validator
from of_tui.validation import as_float, as_int, vector_values


def test_choose_validator_treats_real_vector_as_vector() -> None:
    validator, label = _choose_validator("U", "(1 2 3)")
    assert validator is vector_values
    assert label == "vector"


def test_choose_validator_does_not_treat_scheme_as_vector() -> None:
    value = "div(tauMC) Gauss linear"
    validator, label = _choose_validator("divScheme", value)
    # Should fall back to generic text validator, not vector_values.
    assert validator is not vector_values
    assert label == "text"


def test_choose_validator_uses_float_for_scalar_with_decimal() -> None:
    value = "preMij          0.014;"
    validator, label = _choose_validator("preMij", value)
    assert validator is as_float
    assert label == "float"


def test_choose_validator_uses_int_for_scalar_integer() -> None:
    value = "5;"
    validator, label = _choose_validator("startFrom", value)
    assert validator is as_int
    assert label == "integer"
