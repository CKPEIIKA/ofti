from pathlib import Path

from ofti.core.dict_compare import compare_case_dicts


def _write_control_dict(path: Path, keys: dict[str, str]) -> None:
    lines = [
        "FoamFile",
        "{",
        "    version 2.0;",
        "    format ascii;",
        "    class dictionary;",
        '    location "system";',
        "    object controlDict;",
        "}",
    ]
    for key, value in keys.items():
        lines.append(f"{key} {value};")
    lines.append("")
    path.write_text("\n".join(lines))


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


def test_compare_case_dicts_detects_value_diffs(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    (left / "system").mkdir(parents=True)
    (right / "system").mkdir(parents=True)
    _write_control_dict(left / "system" / "controlDict", {"application": "simpleFoam", "endTime": "100"})
    _write_control_dict(right / "system" / "controlDict", {"application": "rhoSimpleFoam", "endTime": "100"})

    diffs = compare_case_dicts(left, right)
    diff = next(d for d in diffs if d.rel_path == "system/controlDict")
    assert diff.value_diffs
    row = next(item for item in diff.value_diffs if item.key == "application")
    assert row.left == "simpleFoam"
    assert row.right == "rhoSimpleFoam"


def test_compare_case_dicts_detects_raw_file_hash_change(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "maxCoSchedule.dat").write_text("1 2 3\n")
    (right / "maxCoSchedule.dat").write_text("1 2 4\n")

    diffs = compare_case_dicts(left, right)
    diff = next(d for d in diffs if d.rel_path == "maxCoSchedule.dat")
    assert diff.kind == "file"
    assert diff.left_hash != diff.right_hash
