from ofti.core.validation import field_value


def test_field_value_requires_uniform_or_nonuniform() -> None:
    assert field_value("uniform 0") is None
    assert field_value("uniform (1 0 0)") is None
    assert field_value("nonuniform List<scalar> 0()") is None
    assert field_value("nonuniform (1 2 3)") is None
    assert field_value("0") is not None
    assert field_value("") is not None
