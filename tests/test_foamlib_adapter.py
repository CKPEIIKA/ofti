import gzip
import shutil
import struct
import warnings
from pathlib import Path

import pytest

from ofti.core import field_io
from ofti.foamlib import adapter as foamlib_integration


def _require_foamlib_field_reader() -> None:
    if not foamlib_integration.FOAMLIB_AVAILABLE:
        pytest.skip("foamlib field parser is unavailable in this test process")


def test_foamlib_integration_available() -> None:
    assert foamlib_integration.available() is True


def test_foamlib_integration_list_subkeys() -> None:
    file_path = Path("examples/of_example/0/U")
    subkeys = foamlib_integration.list_subkeys(file_path, "boundaryField")
    assert "inlet" in subkeys


def test_foamlib_integration_read_write(tmp_path: Path) -> None:
    src = Path("examples/pitzDaily/system/controlDict")
    if not src.is_file():
        pytest.skip("examples/pitzDaily not available")
    dst = tmp_path / "controlDict"
    shutil.copy(src, dst)

    value = foamlib_integration.read_entry(dst, "application")
    assert "".join(value.split())

    assert foamlib_integration.write_entry(dst, "application", "simpleFoam") is True
    updated = foamlib_integration.read_entry(dst, "application").strip()
    assert updated.rstrip(";") == "simpleFoam"


def test_foamlib_integration_parse_boundary_file() -> None:
    boundary = Path("examples/pitzDaily/constant/polyMesh/boundary")
    if not boundary.is_file():
        pytest.skip("examples/pitzDaily not available")
    patches, types = foamlib_integration.parse_boundary_file(boundary)
    assert "inlet" in patches
    assert types.get("inlet") in {"patch", "wall", "empty"}


def test_foamlib_integration_write_uniform_vector(tmp_path: Path) -> None:
    src = Path("examples/of_example/0/U")
    dst = tmp_path / "U"
    shutil.copy(src, dst)

    assert foamlib_integration.write_entry(
        dst,
        "boundaryField.inlet.value",
        "uniform (1 0 0)",
    )
    text = dst.read_text()
    assert "value uniform (1.0 0.0 0.0);" in text


def test_foamlib_integration_writes_boolean_without_string_conversion_warning(tmp_path: Path) -> None:
    src = Path("examples/cavity/system/controlDict")
    dst = tmp_path / "controlDict"
    shutil.copy(src, dst)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert foamlib_integration.write_entry(dst, "runTimeModifiable", "false") is True
        assert foamlib_integration.write_entry(dst, "adjustTimeStep", "yes") is True

    assert not [warning for warning in caught if "will be stored as" in str(warning.message)]
    stored = foamlib_integration.read_entry(dst, "runTimeModifiable").strip().rstrip(";").lower()
    assert stored in {"false", "no"}
    text = dst.read_text(encoding="utf-8")
    assert any(f"runTimeModifiable {value};" in text for value in ("false", "no"))
    assert foamlib_integration.read_entry(dst, "adjustTimeStep").strip().rstrip(";").lower() in {"true", "yes"}


def test_foamlib_node_type_details_for_field_vectors() -> None:
    path = Path("examples/of_example/0/U")
    node = foamlib_integration.read_field_entry_node(path, "boundaryField.inlet.value")

    assert foamlib_integration.node_type_label(node) == "vector"
    details = foamlib_integration.node_type_details(node)
    assert "foamlib type: vector" in details
    # shape:/dtype: lines only appear when foamlib backs the value with a numpy
    # array; some environments parse "uniform (1 0 0)" to a plain tuple. Assert
    # the stable contract instead of the numpy-specific enrichment.
    assert any(line.startswith("python type:") for line in details)


def test_foamlib_reads_compressed_binary_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_foamlib_field_reader()
    field_path = tmp_path / "p.gz"
    payload = (
        b'FoamFile { format binary; arch "LSB;label=32;scalar=64"; class volScalarField; }\n'
        b"internalField nonuniform List<scalar> 2\n(" + struct.pack("<2d", 1.25, -2.5) + b");\nboundaryField {}\n"
    )
    with gzip.open(field_path, "wb") as compressed:
        compressed.write(payload)

    original_read = foamlib_integration.read_field_entry_node
    calls: list[tuple[Path, str]] = []

    def read_field_entry(path: Path, key: str) -> object:
        calls.append((path, key))
        return original_read(path, key)

    monkeypatch.setattr(foamlib_integration, "read_field_entry_node", read_field_entry)

    assert foamlib_integration.is_field_file(field_path) is True
    data = field_io.read_field_values(field_path)

    assert calls == [(field_path, "internalField")]
    assert data.values == [(1.25,), (-2.5,)]


def test_foamlib_reads_compressed_binary_boundary_value(tmp_path: Path) -> None:
    _require_foamlib_field_reader()
    field_path = tmp_path / "p.gz"
    payload = (
        b'FoamFile { format binary; arch "LSB;label=32;scalar=64"; class volScalarField; }\n'
        b"internalField nonuniform List<scalar> 1 ("
        + struct.pack("<d", 1.25)
        + b");\nboundaryField { inlet { type fixedValue; value uniform 2.5; } }\n"
    )
    with gzip.open(field_path, "wb") as compressed:
        compressed.write(payload)

    value = foamlib_integration.read_field_entry_node(field_path, "boundaryField.inlet.value")

    assert value == 2.5


def test_foamlib_field_detection_rejects_invalid_gzip(tmp_path: Path) -> None:
    field_path = tmp_path / "p.gz"
    field_path.write_bytes(b"invalid gzip header")

    assert foamlib_integration.is_foam_file(field_path) is False
    assert foamlib_integration.is_field_file(field_path) is False


def test_foamlib_file_dict_uses_case_relative_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    control = case / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    (case / "constant").mkdir()
    control.write_text("application simpleFoam;\n")
    calls: list[tuple[Path, Path]] = []

    class _FakeFoamFile:
        def as_dict(self, *, include_header: bool = False) -> dict[str, object]:
            return {"application": "simpleFoam", "header": {"included": include_header}}

    class _FakeCase:
        def __init__(self, path: Path) -> None:
            self.path = path

        def file(self, path: Path) -> _FakeFoamFile:
            calls.append((self.path, path))
            return _FakeFoamFile()

    monkeypatch.setattr(foamlib_integration, "FOAMLIB_AVAILABLE", True)
    monkeypatch.setattr(foamlib_integration, "FoamCase", _FakeCase)

    payload = foamlib_integration.read_file_dict(control, include_header=True)

    assert calls == [(case.resolve(), Path("system/controlDict"))]
    assert payload["application"] == "simpleFoam"
    assert payload["header"] == {"included": True}


def test_foamlib_fallback_file_dict_and_field_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = tmp_path / "case"
    control = case / "system" / "controlDict"
    field = case / "1" / "T"
    control.parent.mkdir(parents=True)
    field.parent.mkdir(parents=True)
    control.write_text("application simpleFoam;\n")
    field.write_text(
        "\n".join(
            [
                "FoamFile{ version 2.0; format ascii; class volScalarField; }",
                "dimensions [0 0 0 1 0 0 0];",
                "internalField nonuniform List<scalar>",
                "3",
                "(",
                "300",
                "301",
                "302",
                ")",
                ";",
                "boundaryField { inlet { type fixedValue; value uniform 310; } }",
            ],
        ),
    )
    monkeypatch.setattr(foamlib_integration, "FOAMLIB_AVAILABLE", False)

    payload = foamlib_integration.read_file_dict(control)
    internal = foamlib_integration.read_field_entry_node(field, "internalField")

    assert payload["application"] == "simpleFoam"
    tolist = getattr(internal, "tolist", None)
    assert callable(tolist)
    assert tolist() == [300.0, 301.0, 302.0]
    assert foamlib_integration.read_field_entry(field, "boundaryField.inlet.value") == "310.0;"
    assert foamlib_integration.node_type_label("uniform (1 0 0);") == "vector"


def test_foamlib_file_dict_uses_case_relative_without_foamfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = tmp_path / "case"
    control = case / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    (case / "constant").mkdir()
    control.write_text("application simpleFoam;\n")
    calls: list[tuple[Path, Path]] = []

    class _FakeFoamFile:
        def as_dict(self, *, include_header: bool = False) -> dict[str, object]:
            return {"application": "simpleFoam", "header": {"included": include_header}}

    class _FakeCase:
        def __init__(self, path: Path) -> None:
            self.path = path

        def file(self, path: Path) -> _FakeFoamFile:
            calls.append((self.path, path))
            return _FakeFoamFile()

    monkeypatch.setattr(foamlib_integration, "FOAMLIB_AVAILABLE", True)
    monkeypatch.setattr(foamlib_integration, "FoamFile", None)
    monkeypatch.setattr(foamlib_integration, "FoamCase", _FakeCase)

    payload = foamlib_integration.read_file_dict(control, include_header=True)

    assert calls == [(case.resolve(), Path("system/controlDict"))]
    assert payload["application"] == "simpleFoam"
