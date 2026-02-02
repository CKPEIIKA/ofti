from __future__ import annotations

from pathlib import Path

from ofti.tools import runner


def test_normalize_tool_name_strips_and_lowercases() -> None:
    assert runner._normalize_tool_name("  BlockMesh  ") == "blockmesh"
    assert runner._normalize_tool_name("post:Process") == "post:process"


def test_list_tool_commands_includes_basics(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    commands = runner.list_tool_commands(case_dir)

    assert "blockmesh" in commands
    assert "checkmesh" in commands
    assert "foamdictionary" not in commands
