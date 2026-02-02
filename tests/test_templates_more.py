from __future__ import annotations

from pathlib import Path

from ofti.core import templates


def test_find_example_file_returns_path() -> None:
    rel = Path("system") / "controlDict"
    path = templates.find_example_file(rel)
    assert path is not None
    assert path.name == "controlDict"


def test_load_example_template_missing() -> None:
    rel = Path("does") / "not" / "exist"
    assert templates.load_example_template(rel) is None
