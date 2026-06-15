from pathlib import Path

import pytest

from ofti.core.entry_meta import get_entry_metadata
from ofti.foamlib import adapter as foamlib_integration


@pytest.mark.skipif(not foamlib_integration.available(), reason="foamlib required")
def test_entry_metadata_foamlib_type_labels() -> None:
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]] = {}
    field_path = Path("examples/of_example/0/U")

    value, type_label, subkeys, _comments, _info_lines, _validator = get_entry_metadata(
        cache, field_path, "boundaryField",
    )
    assert value
    assert type_label == "dict"
    assert "inlet" in subkeys

    _value, type_label, _subkeys, _comments, _info_lines, _validator = get_entry_metadata(
        cache, field_path, "dimensions",
    )
    assert type_label == "dimensions"
    assert any(line.startswith("foamlib type: dimensions") for line in _info_lines)

    _value, type_label, _subkeys, _comments, info_lines, _validator = get_entry_metadata(
        cache, field_path, "boundaryField.inlet.value",
    )
    assert type_label == "vector"
    # shape:/dtype: lines depend on foamlib returning a numpy array; assert the
    # stable type contract so the test holds whether the value parses to an
    # ndarray or a plain tuple.
    assert any(line.startswith("foamlib type: vector") for line in info_lines)
