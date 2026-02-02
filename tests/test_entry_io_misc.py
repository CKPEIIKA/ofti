from __future__ import annotations

from pathlib import Path

from ofti.core import entry_io


def test_compact_value_formats() -> None:
    assert entry_io._compact_value(None) == "<unknown>"
    assert entry_io._compact_value("") == "<empty>"
    long_text = "word " * 50
    compact = entry_io._compact_value(long_text, max_len=20)
    assert compact.endswith("...")


def test_find_case_root(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    target = case_dir / "0" / "U"
    target.parent.mkdir(parents=True)
    target.write_text("FoamFile{}\n")

    assert entry_io._find_case_root(target) == case_dir
    assert entry_io._find_case_root(tmp_path / "random") is None
