import shutil
from pathlib import Path

import pytest

from ofti.foamlib import adapter as foamlib_integration


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
