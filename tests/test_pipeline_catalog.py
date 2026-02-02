from pathlib import Path

from ofti.tools import pipeline


def test_pipeline_catalog_includes_common_steps(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    options = pipeline._pipeline_tool_catalog(case_dir)
    labels = [name for name, _cmd in options]

    assert "blockMesh" in labels
    assert "topoSet" in labels
    assert "setFields" in labels


def test_read_pipeline_commands_parses_lines(tmp_path: Path) -> None:
    path = tmp_path / "Allrun"
    path.write_text("#!/bin/bash\n# OFTI-PIPELINE\n\nblockMesh\n# comment\nsnappyHexMesh\n")

    commands, errors = pipeline._read_pipeline_commands(path)

    assert not errors
    assert commands == [["blockMesh"], ["snappyHexMesh"]]
