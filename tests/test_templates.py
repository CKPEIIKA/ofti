from __future__ import annotations

from pathlib import Path

from ofti.core import templates


def test_load_example_template_reads_file() -> None:
    rel = Path("system") / "controlDict"
    text = templates.load_example_template(rel)
    assert text is not None
    assert "application" in text


def test_write_example_template(tmp_path: Path) -> None:
    dest = tmp_path / "system" / "controlDict"
    ok = templates.write_example_template(dest, Path("system") / "controlDict")
    assert ok
    assert dest.is_file()
