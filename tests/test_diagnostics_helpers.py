from pathlib import Path

from ofti.tools import diagnostics


def test_directory_size_and_human_size(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("1234")

    size = diagnostics._directory_size(tmp_path)
    assert size >= 4

    assert diagnostics._human_size(0).startswith("0")
    assert diagnostics._human_size(1024).endswith("B")
