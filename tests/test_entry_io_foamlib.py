from __future__ import annotations

from pathlib import Path

import pytest

from ofti.core import entry_io
from ofti.foamlib import adapter as foamlib_integration


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required for entry_io tests",
)
def test_entry_io_reads_and_lists_with_foamlib(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    field = case_dir / "0" / "U"
    field.parent.mkdir(parents=True)
    field.write_text(
        'FoamFile{version 2.0;format ascii;class volScalarField;location "0";object U;}\n'
        "alpha 1.0;\n"
        "boundaryField{ inlet{ type fixedValue; value uniform 0; } }\n",
    )

    assert "alpha" in entry_io.list_keywords(field)
    assert "inlet" in entry_io.list_subkeys(field, "boundaryField")
    assert entry_io.read_entry(field, "alpha").startswith("1")


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required for entry_io tests",
)
def test_entry_io_write_logs_changes(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    field = case_dir / "0" / "p"
    field.parent.mkdir(parents=True)
    field.write_text(
        'FoamFile{version 2.0;format ascii;class volScalarField;location "0";object p;}\n'
        "p 1;\n",
    )

    assert entry_io.write_entry(field, "p", "2")
    log_path = case_dir / ".ofti" / "edits.log"
    assert log_path.is_file()
    assert "p:" in log_path.read_text()


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required for entry_io tests",
)
def test_entry_io_field_helpers(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    field = case_dir / "0" / "T"
    field.parent.mkdir(parents=True)
    field.write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class volScalarField;",
                '    location "0";',
                "    object T;",
                "}",
                "dimensions [0 0 0 0 0 0 0];",
                "internalField uniform 300;",
                "boundaryField",
                "{",
                "    inlet",
                "    {",
                "        type fixedValue;",
                "        value uniform 310;",
                "    }",
                "}",
            ],
        ),
    )

    assert entry_io.read_field_entry(field, "internalField").startswith("uniform 300")
    assert entry_io.read_dimensions(field).startswith("[0 0 0 0 0 0 0]")
    assert "inlet" in entry_io.read_boundary_field(field)


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required for entry_io tests",
)
def test_foamfieldfile_nonuniform_time_dir_round_trip(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    field = case_dir / "1" / "T"
    field.parent.mkdir(parents=True)
    field.write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class volScalarField;",
                '    location "1";',
                "    object T;",
                "}",
                "dimensions [0 0 0 1 0 0 0];",
                "internalField nonuniform List<scalar>",
                "3",
                "(",
                "300",
                "301",
                "302",
                ")",
                ";",
                "boundaryField",
                "{",
                "    inlet",
                "    {",
                "        type fixedValue;",
                "        value uniform 310;",
                "    }",
                "    outlet",
                "    {",
                "        type zeroGradient;",
                "    }",
                "}",
            ],
        ),
    )

    internal = foamlib_integration.read_field_entry_node(field, "internalField")
    assert getattr(internal, "tolist", list)() == [300.0, 301.0, 302.0]
    assert foamlib_integration.read_field_entry(field, "boundaryField.inlet.value") == "310.0;"

    assert entry_io.write_field_entry(
        field,
        "internalField",
        "nonuniform List<scalar>\n3\n(\n400\n401\n402\n)\n;",
    )
    assert entry_io.write_field_entry(field, "boundaryField.inlet.value", "uniform 315")

    updated = foamlib_integration.read_field_entry_node(field, "internalField")
    assert getattr(updated, "tolist", list)() == [400.0, 401.0, 402.0]
    assert foamlib_integration.read_field_entry(field, "boundaryField.inlet.value") == "315.0;"
    assert entry_io.write_field_entry(field, "internalField", "uniform 350")
    assert entry_io.read_field_entry(field, "internalField").startswith("uniform 350")


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required for entry_io tests",
)
def test_entry_io_time_dir_field_round_trip_with_foamlib(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    field = case_dir / "1.5" / "U"
    field.parent.mkdir(parents=True)
    field.write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class volVectorField;",
                '    location "1.5";',
                "    object U;",
                "}",
                "dimensions [0 1 -1 0 0 0 0];",
                "internalField uniform (0 0 0);",
                "boundaryField",
                "{",
                "    inlet",
                "    {",
                "        type fixedValue;",
                "        value uniform (1 0 0);",
                "    }",
                "}",
            ],
        ),
    )

    assert entry_io.write_time_field_entry(case_dir, "1.5", "U", "internalField", "uniform (2 0 0)")
    rows = entry_io.read_time_field_entries(case_dir, "1.5", "U", ["dimensions", "internalField"])

    assert rows["dimensions"].startswith("[0 1 -1 0 0 0 0]")
    assert rows["internalField"].startswith("uniform (2")
