from __future__ import annotations

from pathlib import Path

from ofti.core import boundary


def test_zero_dir_prefers_zero(tmp_path: Path) -> None:
    zero = tmp_path / "0"
    zero.mkdir()
    (tmp_path / "0.orig").mkdir()
    assert boundary.zero_dir(tmp_path) == zero


def test_list_field_files_filters(tmp_path: Path) -> None:
    zero = tmp_path / "0"
    zero.mkdir()
    (zero / ".hidden").write_text("ignore")
    (zero / "U").write_text("field")
    (zero / "p").write_text("field")
    (zero / "temp~").write_text("backup")

    fields = boundary.list_field_files(tmp_path)
    assert fields == ["U", "p"]
