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


def test_integer_entries_are_written_as_integers(tmp_path: Path) -> None:
    # OpenFOAM reads labels strictly: "numberOfSubdomains 2.0;" or "n (2.0 1.0 1.0);"
    # break decomposePar, and a float write also defeated OFTI's own re-read.
    assert type(foamlib_integration._parse_uniform_value("5")) is int
    vector = foamlib_integration._parse_uniform_value("(2 1 1e-3)")
    assert isinstance(vector, list)
    assert [type(value) for value in vector] == [int, int, float]
    assert type(foamlib_integration._parse_uniform_value("2.0")) is float

    target = tmp_path / "decomposeParDict"
    target.write_text(
        "FoamFile\n{\n    version 2.0;\n    format ascii;\n    class dictionary;\n    object decomposeParDict;\n}\n"
        "numberOfSubdomains  9;\nmethod scotch;\n",
    )

    assert foamlib_integration.write_entry(target, "numberOfSubdomains", "2")
    text = target.read_text()
    assert text.count("numberOfSubdomains") == 1
    assert "2.0" not in text.split("numberOfSubdomains", 1)[1]
