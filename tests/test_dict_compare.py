from pathlib import Path

import pytest

from ofti import foamlib_adapter
from ofti.core.dict_compare import compare_case_dicts


def _write_control_dict(path: Path, keys: dict[str, str]) -> None:
    lines = [
        "FoamFile",
        "{",
        "    version 2.0;",
        "    format ascii;",
        "    class dictionary;",
        "    location \"system\";",
        "    object controlDict;",
        "}",
    ]
    for key, value in keys.items():
        lines.append(f"{key} {value};")
    lines.append("")
    path.write_text("\n".join(lines))


@pytest.mark.skipif(not foamlib_adapter.available(), reason="foamlib required")
def test_compare_case_dicts_detects_missing_keys(tmp_path: Path) -> None:
    left = tmp_path / "case_left"
    right = tmp_path / "case_right"
    (left / "system").mkdir(parents=True)
    (right / "system").mkdir(parents=True)

    _write_control_dict(
        left / "system" / "controlDict",
        {"application": "simpleFoam", "startTime": "0"},
    )
    _write_control_dict(
        right / "system" / "controlDict",
        {"application": "simpleFoam", "endTime": "100"},
    )

    diffs = compare_case_dicts(left, right)
    assert diffs
    diff = next(d for d in diffs if d.rel_path == "system/controlDict")
    assert "endTime" in diff.missing_in_left
    assert "startTime" in diff.missing_in_right
