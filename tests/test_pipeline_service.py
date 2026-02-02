from __future__ import annotations

from pathlib import Path

from ofti.core import pipeline as pipeline_service


def test_pipeline_round_trip(tmp_path: Path) -> None:
    path = tmp_path / pipeline_service.PIPELINE_FILENAME
    commands = [
        ["echo", "hello"],
        ["ofti:set", "system/controlDict", "endTime", "1000"],
        ["echo", "uniform (1 0 0)"],
    ]

    pipeline_service.write_pipeline_file(path, commands)
    read_back, errors = pipeline_service.read_pipeline_commands(path)

    assert errors == []
    assert read_back == commands


def test_pipeline_missing_header(tmp_path: Path) -> None:
    path = tmp_path / pipeline_service.PIPELINE_FILENAME
    path.write_text("#!/bin/bash\necho hello\n")

    read_back, errors = pipeline_service.read_pipeline_commands(path)

    assert read_back == []
    assert errors


def test_pipeline_run_echo(tmp_path: Path) -> None:
    commands = [["echo", "hello"]]
    results = pipeline_service.run_pipeline_commands(tmp_path, commands)

    assert results
    assert results[0].startswith("$ echo hello")
    assert any("status: OK" in line for line in results)
