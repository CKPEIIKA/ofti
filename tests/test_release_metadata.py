from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

import pytest

from ofti import __version__
from ofti.app import cli, cli_tools
from ofti.app.cli_adapters import main as main_adapter
from ofti.app.cli_adapters.main import build_parser, ofti_version

ROOT = Path(__file__).parents[1]
TOP_LEVEL_COMMANDS = {
    "knife",
    "plot",
    "watch",
    "run",
    "bundle",
    "result",
    "plugins",
    "version",
}


def _subcommands(parser: argparse.ArgumentParser) -> set[str]:
    action = next(item for item in parser._actions if isinstance(item, argparse._SubParsersAction))
    return set(action.choices)


def test_version_and_license_have_one_source_contract() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert "version" not in project["project"]
    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "ofti.__version__"}
    assert project["project"]["license"] == "GPL-3.0-or-later"
    assert ofti_version() == __version__
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in (ROOT / "LICENSE").read_text()
    for plugin in ("ofti-hy2foam", "hy2foam-mod"):
        metadata = tomllib.loads((ROOT / "plugins" / plugin / "pyproject.toml").read_text())
        assert metadata["project"]["license"] == "GPL-3.0-or-later"


def test_cli_tools_keeps_only_the_supported_compatibility_surface() -> None:
    assert cli_tools.__all__ == ["build_parser", "main", "ofti_version"]
    assert cli_tools.build_parser is main_adapter.build_parser
    assert cli_tools.main is main_adapter.main
    assert cli_tools.ofti_version is main_adapter.ofti_version


def test_public_command_groups_match_parser_and_readme() -> None:
    readme = (ROOT / "README.md").read_text()

    assert cli._CLI_TOOLS_GROUPS == TOP_LEVEL_COMMANDS
    assert _subcommands(build_parser()) == TOP_LEVEL_COMMANDS
    for command in TOP_LEVEL_COMMANDS:
        assert f"`ofti {command}" in readme


@pytest.mark.parametrize("command", sorted(TOP_LEVEL_COMMANDS))
def test_public_entry_point_exposes_help_for_every_command(command: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main([command, "-h"])

    assert exc_info.value.code == 0


def test_result_help_is_the_result_group_not_top_level_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["result", "--help"])

    output = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert "usage: ofti result" in output
    assert "{pack,unpack}" in output
    assert "interactive curses TUI" not in output


def test_readme_stays_compact_and_points_to_detailed_docs() -> None:
    lines = (ROOT / "README.md").read_text().splitlines()

    assert len(lines) < 250
    assert "[docs/cli.md](docs/cli.md)" in "\n".join(lines)
    assert "[docs/tui.md](docs/tui.md)" in "\n".join(lines)
