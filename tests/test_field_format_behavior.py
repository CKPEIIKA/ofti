"""Format coverage for the OFTI-owned fallback field parser.

These tests exercise ``field_io.read_field_values`` with the foamlib backend
disabled, so they pin the behaviour of the pure-Python fallback for every
OpenFOAM field rank, surface fields, binary rejection, decomposed processor
fields, patch values, and missing-patch handling.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ofti.core import field_io


@pytest.fixture(autouse=True)
def _no_foamlib(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the pure-Python fallback so coverage does not depend on foamlib.
    monkeypatch.setattr(field_io.foamlib_integration, "available", lambda: False)


def _write_field(path: Path, class_name: str, internal: str, boundary: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"FoamFile{{ version 2.0; format ascii; class {class_name}; }}\n"
        f"internalField {internal};\n"
        f"boundaryField{boundary}\n",
        encoding="utf-8",
    )
    return path


def _nonuniform(kind: str, rows: list[str]) -> str:
    body = "\n".join(rows)
    return f"nonuniform List<{kind}>\n{len(rows)}\n(\n{body}\n)"


def test_scalar_field_is_read_as_one_component(tmp_path: Path) -> None:
    path = _write_field(tmp_path / "p", "volScalarField", _nonuniform("scalar", ["1", "2", "3"]))

    data = field_io.read_field_values(path)

    assert data.kind == "scalar"
    assert data.component_count == 1
    assert data.count == 3


def test_vector_field_groups_three_components(tmp_path: Path) -> None:
    rows = ["(1 0 0)", "(0 2 0)"]
    path = _write_field(tmp_path / "U", "volVectorField", _nonuniform("vector", rows))

    data = field_io.read_field_values(path)

    assert data.kind == "vector"
    assert data.component_count == 3
    assert data.values[1] == (0.0, 2.0, 0.0)


def test_symmtensor_field_groups_six_components(tmp_path: Path) -> None:
    rows = ["(1 2 3 4 5 6)", "(7 8 9 10 11 12)"]
    path = _write_field(tmp_path / "sigma", "volSymmTensorField", _nonuniform("symmTensor", rows))

    data = field_io.read_field_values(path)

    assert data.kind == "numeric"
    assert data.component_count == 6
    assert data.count == 2
    assert data.values[0] == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)


def test_tensor_field_groups_nine_components(tmp_path: Path) -> None:
    rows = ["(1 0 0 0 1 0 0 0 1)"]
    path = _write_field(tmp_path / "gradU", "volTensorField", _nonuniform("tensor", rows))

    data = field_io.read_field_values(path)

    assert data.kind == "numeric"
    assert data.component_count == 9
    assert data.values[0][0] == 1.0


def test_uniform_tensor_keeps_all_components(tmp_path: Path) -> None:
    path = _write_field(tmp_path / "T", "volTensorField", "uniform (1 0 0 0 1 0 0 0 1)")

    data = field_io.read_field_values(path)

    assert data.uniform is True
    assert data.component_count == 9


def test_surface_scalar_field_internal_values_are_read(tmp_path: Path) -> None:
    # surfaceScalarField stores face fluxes but uses the same internalField shape.
    path = _write_field(tmp_path / "phi", "surfaceScalarField", _nonuniform("scalar", ["0.1", "0.2"]))

    data = field_io.read_field_values(path)

    assert data.kind == "scalar"
    assert data.count == 2


def test_binary_format_field_is_rejected_gracefully(tmp_path: Path) -> None:
    path = tmp_path / "U"
    path.write_bytes(
        b"FoamFile{ format binary; class volVectorField; }\n"
        b"internalField nonuniform List<vector> 2 (\x00\x01\x02\x03\x04\x05);\n"
        b"boundaryField{}\n",
    )

    with pytest.raises(ValueError, match="internalField"):
        field_io.read_field_values(path)


def test_missing_patch_raises_value_error(tmp_path: Path) -> None:
    boundary = "{ inlet { type fixedValue; value uniform 1; } }"
    path = _write_field(tmp_path / "p", "volScalarField", "uniform 0", boundary=boundary)

    with pytest.raises(ValueError, match="missing patch"):
        field_io.read_field_values(path, patch="outlet")


def test_patch_uniform_value_is_read(tmp_path: Path) -> None:
    boundary = "{ outlet { type fixedValue; value uniform 5; } }"
    path = _write_field(tmp_path / "p", "volScalarField", "uniform 0", boundary=boundary)

    data = field_io.read_field_values(path, patch="outlet")

    assert data.values == [(5.0,)]


def test_decomposed_processor_fields_are_aggregated(tmp_path: Path) -> None:
    case = tmp_path / "case"
    for proc, rows in (("processor0", ["1", "2"]), ("processor1", ["3", "4", "5"])):
        _write_field(case / proc / "0" / "p", "volScalarField", _nonuniform("scalar", rows))

    data = field_io.read_field_values(case / "processor0" / "0" / "p")

    # Values from every subdomain are concatenated into one field.
    assert data.count == 5
    assert data.uniform is False
