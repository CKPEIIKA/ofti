from pathlib import Path

from ofti.foamlib_adapter import read_entry
from ofti.foamlib_parametric import build_parametric_cases


def test_build_parametric_cases(tmp_path: Path) -> None:
    case_path = Path("examples/pitzDaily")
    created = build_parametric_cases(
        case_path,
        Path("system/controlDict"),
        "application",
        ["simpleFoam"],
        output_root=tmp_path,
    )
    assert len(created) == 1
    new_case = created[0]
    assert (new_case / "system" / "controlDict").is_file()
    value = read_entry(new_case / "system" / "controlDict", "application")
    assert value.strip().rstrip(";") == "simpleFoam"
