from __future__ import annotations

from pathlib import Path

from ofti.foamlib import fallback


def test_parse_boundary_file_handles_inline_and_multiline(tmp_path: Path) -> None:
    boundary = tmp_path / "boundary"
    boundary.write_text(
        "\n".join(
            [
                "FoamFile{version 2.0; object boundary;}",
                "2",
                "(",
                " inlet { type patch; nFaces 1; startFace 0; }",
                " outlet",
                " {",
                "   type wall;",
                "   nFaces 1;",
                "   startFace 1;",
                " }",
                ")",
            ],
        ),
    )

    patches, patch_types = fallback.parse_boundary_file(boundary)

    assert patches == ["inlet", "outlet"]
    assert patch_types["inlet"] == "patch"
    assert patch_types["outlet"] == "wall"


def test_write_entry_normalizes_uniform_vector(tmp_path: Path) -> None:
    field = tmp_path / "U"
    field.write_text(
        "\n".join(
            [
                "FoamFile{version 2.0; object U;}",
                "boundaryField",
                "{",
                "    inlet",
                "    {",
                "        type fixedValue;",
                "        value uniform (0 0 0);",
                "    }",
                "}",
            ],
        ),
    )

    assert fallback.write_entry(field, "boundaryField.inlet.value", "uniform (1 0 0)")
    text = field.read_text()
    assert "value uniform (1.0 0.0 0.0);" in text


def test_read_entry_dimensions_keeps_brackets(tmp_path: Path) -> None:
    dict_path = tmp_path / "T"
    dict_path.write_text(
        "\n".join(
            [
                "FoamFile{version 2.0; object T;}",
                "dimensions [0 1 -1 0 0 0 0];",
            ],
        ),
    )

    assert fallback.read_entry(dict_path, "dimensions") == "[0 1 -1 0 0 0 0]"


def test_rename_boundary_field_patch_updates_name(tmp_path: Path) -> None:
    field = tmp_path / "p"
    field.write_text(
        "\n".join(
            [
                "FoamFile{version 2.0; object p;}",
                "boundaryField",
                "{",
                "    inlet",
                "    {",
                "        type fixedValue;",
                "        value uniform 0;",
                "    }",
                "}",
            ],
        ),
    )

    assert fallback.rename_boundary_field_patch(field, "inlet", "inflow")
    text = field.read_text()
    assert "inflow" in text
    assert "inlet" not in text
