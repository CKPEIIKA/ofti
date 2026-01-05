from pathlib import Path

from tui.openfoam import discover_case_files


def test_discover_case_files_basic(tmp_path: Path) -> None:
    case = tmp_path / "case"
    system = case / "system"
    constant = case / "constant"
    zero = case / "0"
    system.mkdir(parents=True)
    constant.mkdir()
    zero.mkdir()

    (system / "controlDict").write_text("controlDict;")
    (constant / "thermophysicalProperties").write_text("thermo;")
    (zero / "p").write_text("p;")

    result = discover_case_files(case)

    assert (system / "controlDict") in result["system"]
    assert (constant / "thermophysicalProperties") in result["constant"]
    assert (zero / "p") in result["0*"]

