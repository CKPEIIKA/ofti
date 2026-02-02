from pathlib import Path

import pytest

from ofti.foamlib.adapter import read_entry
from ofti.foamlib.parametric import build_parametric_cases


def test_build_parametric_cases(tmp_path: Path) -> None:
    case_path = Path("examples/pitzDaily")
    if not case_path.is_dir():
        pytest.skip("examples/pitzDaily not available")
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
