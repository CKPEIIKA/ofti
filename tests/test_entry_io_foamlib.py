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
        "FoamFile{version 2.0;format ascii;class volScalarField;location \"0\";object U;}\n"
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
        "FoamFile{version 2.0;format ascii;class volScalarField;location \"0\";object p;}\n"
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
                "    location \"0\";",
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
    assert entry_io.write_field_entry(field, "internalField", "uniform 350")
    assert entry_io.read_field_entry(field, "internalField").startswith("uniform 350")
