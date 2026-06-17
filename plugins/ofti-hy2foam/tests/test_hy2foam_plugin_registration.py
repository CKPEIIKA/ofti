# ruff: noqa: INP001
from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from ofti.app.cli_adapters.command_builder import build_spec_parser
from ofti.plugins import PluginRegistry

PLUGIN_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SRC))

from ofti_hy2foam.plugin import register  # noqa: E402


def test_hy2foam_plugin_registers_presets_profile_and_charge_command() -> None:
    registry = PluginRegistry()

    register(registry)

    assert registry.presets["air5"].source == "ofti-hy2foam"
    assert registry.presets["air11"].fields[-2:] == ("p", "rho")
    assert registry.presets["hy2foam-transport"].fields[-1] == "qDiff"
    assert registry.presets["hy2foam-2T"].fields == ("Tt", "Tv", "Tov", "e", "ev")
    assert registry.presets["hy2foam-wall"].fields[0] == "wallHeatFlux"
    assert "hy2foam" in registry.physical_profiles
    assert "charge" in registry.knife_commands
    assert "hy2foam-preflight" in registry.knife_commands
    assert "hy2foam-compare-check" in registry.knife_commands
    assert "hy2foam-patch-compare" in registry.knife_commands


def _add_command(sub: Any, command: Any) -> None:
    # Mirror the CLI adapter: prefer a CommandSpec, fall back to add_parser.
    spec_fn = getattr(command, "command_spec", None)
    if callable(spec_fn):
        build_spec_parser(sub, spec_fn())
    else:
        command.add_parser(sub)


def _command_parser(command: Any) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    _add_command(sub, command)
    return parser


@pytest.mark.parametrize(
    "argv",
    [
        ["charge", "case", "--json"],
        ["hy2foam-preflight", "case", "--json"],
        ["hy2foam-compare-check", "left", "right", "--json"],
        ["hy2foam-patch-compare", "left", "right", "--patch", "wall", "--json"],
    ],
)
def test_plugin_commands_accept_json_flag(argv: list[str]) -> None:
    registry = PluginRegistry()
    register(registry)
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    for command in registry.knife_commands.values():
        _add_command(sub, command)

    args = parser.parse_args(argv)

    assert args.json is True


def test_charge_command_json_output_is_valid(tmp_path: Path) -> None:
    registry = PluginRegistry()
    register(registry)
    case = tmp_path / "case"
    (case / "0").mkdir(parents=True)
    parser = _command_parser(registry.knife_commands["charge"])

    args = parser.parse_args(["charge", str(case), "--json"])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = args.func(args)

    payload = json.loads(buffer.getvalue())
    assert code == 0
    assert payload["case"] == str(case)
    assert "charged_species" in payload
    # Plugin JSON goes through the shared output contract.
    assert payload["schema_version"] == 1
    assert "command" in payload
