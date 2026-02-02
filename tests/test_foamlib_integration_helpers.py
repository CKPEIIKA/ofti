from __future__ import annotations

from pathlib import Path

import pytest

from ofti.foamlib import adapter as foamlib_integration


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required",
)
def test_foamlib_parse_uniform_value_and_can_write(tmp_path: Path) -> None:
    assert foamlib_integration._parse_uniform_value("uniform (1 2 3)") == [1.0, 2.0, 3.0]
    assert foamlib_integration._parse_uniform_value("5") == 5.0
    assert foamlib_integration._foamlib_can_write("alpha") is True
    assert foamlib_integration._foamlib_can_write("uniform (1 2 3)") is False


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required",
)
def test_is_foam_file_detects_header(tmp_path: Path) -> None:
    path = tmp_path / "U"
    path.write_text("FoamFile{version 2.0;format ascii;}\n")
    assert foamlib_integration.is_foam_file(path)
