from pathlib import Path

from ofti.tools.pipeline import PIPELINE_HEADER, _read_pipeline_commands


def test_read_pipeline_commands_parses_lines(tmp_path: Path) -> None:
    path = tmp_path / "Allrun"
    path.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                PIPELINE_HEADER,
                "",
                "echo hello",
                "blockMesh -case .",
                "python -c \"print('ok')\"",
            ],
        ),
    )
    commands, errors = _read_pipeline_commands(path)
    assert not errors
    assert commands == [
        ["echo", "hello"],
        ["blockMesh", "-case", "."],
        ["python", "-c", "print('ok')"],
    ]


def test_read_pipeline_commands_reports_errors(tmp_path: Path) -> None:
    path = tmp_path / "Allrun"
    path.write_text("\n".join(["#!/bin/bash", PIPELINE_HEADER, "echo \"unterminated"]))
    commands, errors = _read_pipeline_commands(path)
    assert commands == []
    assert errors
