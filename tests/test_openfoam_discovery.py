from pathlib import Path

from ofti.foam.openfoam import discover_case_files


def test_discover_case_files_basic(tmp_path: Path) -> None:
    case = tmp_path / "case"
    system = case / "system"
    constant = case / "constant"
    zero = case / "0"
    later = case / "0.0001"
    system.mkdir(parents=True)
    constant.mkdir()
    zero.mkdir()
    later.mkdir()

    (system / "controlDict").write_text("controlDict;")
    (constant / "thermophysicalProperties").write_text("thermo;")
    (zero / "p").write_text("p;")
    (later / "T").write_text("T;")

    result = discover_case_files(case)

    assert (system / "controlDict") in result["system"]
    assert (constant / "thermophysicalProperties") in result["constant"]
    assert (zero / "p") in result["0*"]
    assert all((later / "T") not in files for files in result.values())
