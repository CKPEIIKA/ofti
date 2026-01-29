import shutil
from pathlib import Path

from ofti import foamlib_adapter


def test_foamlib_adapter_available() -> None:
    assert foamlib_adapter.available() is True


def test_foamlib_adapter_list_subkeys() -> None:
    file_path = Path("examples/pitzDaily/0/U")
    subkeys = foamlib_adapter.list_subkeys(file_path, "boundaryField")
    assert "inlet" in subkeys


def test_foamlib_adapter_read_write(tmp_path: Path) -> None:
    src = Path("examples/pitzDaily/system/controlDict")
    dst = tmp_path / "controlDict"
    shutil.copy(src, dst)

    value = foamlib_adapter.read_entry(dst, "application")
    assert "".join(value.split())

    assert foamlib_adapter.write_entry(dst, "application", "simpleFoam") is True
    updated = foamlib_adapter.read_entry(dst, "application").strip()
    assert updated.rstrip(";") == "simpleFoam"


def test_foamlib_adapter_parse_boundary_file() -> None:
    boundary = Path("examples/pitzDaily/constant/polyMesh/boundary")
    patches, types = foamlib_adapter.parse_boundary_file(boundary)
    assert "inlet" in patches
    assert types.get("inlet") in {"patch", "wall", "empty"}


def test_foamlib_adapter_write_uniform_vector(tmp_path: Path) -> None:
    src = Path("examples/pitzDaily/0/U")
    dst = tmp_path / "U"
    shutil.copy(src, dst)

    assert foamlib_adapter.write_entry(
        dst,
        "boundaryField.inlet.value",
        "uniform (1 0 0)",
    )
    text = dst.read_text()
    assert "value uniform (1.0 0.0 0.0);" in text
