from pathlib import Path

from ofti.core import entry_meta


def test_detect_type_with_foamlib_numeric_list(monkeypatch) -> None:
    monkeypatch.setattr(entry_meta.foamlib_integration, "available", lambda: True)
    monkeypatch.setattr(entry_meta.foamlib_integration, "is_foam_file", lambda _p: True)
    monkeypatch.setattr(
        entry_meta.foamlib_integration,
        "read_entry_node",
        lambda _p, _k: [1.0, 2.0, 3.0],
    )
    validator, label = entry_meta.detect_type_with_foamlib(
        Path("dummy"),
        "vectorField",
        entry_meta.non_empty,
        "text",
    )
    assert label == "vector"
    assert validator is entry_meta.vector_values


def test_detect_type_with_foamlib_dimension_list(monkeypatch) -> None:
    monkeypatch.setattr(entry_meta.foamlib_integration, "available", lambda: True)
    monkeypatch.setattr(entry_meta.foamlib_integration, "is_foam_file", lambda _p: True)
    monkeypatch.setattr(
        entry_meta.foamlib_integration,
        "read_entry_node",
        lambda _p, _k: [0, 1, -2, 0, 0, 0, 0],
    )
    validator, label = entry_meta.detect_type_with_foamlib(
        Path("dummy"),
        "dimensions",
        entry_meta.non_empty,
        "text",
    )
    assert label == "dimensions"
    assert validator is entry_meta.dimension_set_values
