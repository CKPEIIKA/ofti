from ofti.foam.openfoam import is_scalar_value, looks_like_dict, normalize_scalar_token


def test_is_scalar_value_handles_simple_token() -> None:
    assert is_scalar_value("simpleFoam;") is True
    assert is_scalar_value("application simpleFoam;") is False


def test_looks_like_dict_detects_braces() -> None:
    assert looks_like_dict("{\n  key 1;\n}") is True
    assert looks_like_dict("value;") is False


def test_normalize_scalar_token_handles_prefix() -> None:
    assert normalize_scalar_token("application potentialFoam;") == "potentialFoam"
