from __future__ import annotations

import json

import pytest

from ofti.app import cli_tools
from ofti.core.command_spec import CommandSpec
from ofti.plugins import PluginRecord, PluginRegistry


class EchoCommand:
    def __init__(self, name: str, text: str) -> None:
        self.name = name
        self.text = text

    def command_spec(self) -> CommandSpec:
        return CommandSpec(
            name=self.name,
            summary=f"Print {self.text}",
            handler=self.run,
        )

    def run(self, args: object) -> int:
        del args
        print(self.text)
        return 0


def test_plugins_list_reports_source_version_and_registrations(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry(
        plugins=[
            PluginRecord(
                name="demo",
                entry_point="demo:register",
                distribution="ofti-demo",
                version="1.2.3",
                status="loaded",
                registrations={"run_commands": ("demo-run",)},
            ),
        ],
    )
    registry.add_run_command(EchoCommand("demo-run", "run-ok"))
    monkeypatch.setattr("ofti.app.cli_adapters.main.discover_plugins", lambda: registry)

    code = cli_tools.main(["plugins", "list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["command"] == "plugins list"
    assert payload["plugins"][0]["version"] == "1.2.3"
    assert payload["plugins"][0]["entry_point"] == "demo:register"
    assert payload["plugins"][0]["registrations"]["run_commands"] == ["demo-run"]


def test_plugins_doctor_returns_nonzero_for_load_failure(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry(
        plugins=[
            PluginRecord(
                name="broken",
                entry_point="broken:register",
                distribution=None,
                version=None,
                status="failed",
                errors=("broken: import failed",),
            ),
        ],
        errors=["broken: import failed"],
    )
    monkeypatch.setattr("ofti.app.cli_adapters.main.discover_plugins", lambda: registry)

    code = cli_tools.main(["plugins", "doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["ok"] is False
    assert payload["failed"] == 1
    assert payload["errors"] == ["broken: import failed"]


def test_run_watch_and_result_plugin_commands_dispatch(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry()
    registry.add_run_command(EchoCommand("plugin-run", "run-ok"))
    registry.add_watch_command(EchoCommand("plugin-watch", "watch-ok"))
    registry.add_result_command(EchoCommand("plugin-result", "result-ok"))
    monkeypatch.setattr("ofti.app.cli_adapters.main.discover_plugins", lambda: registry)

    for argv, expected in (
        (["run", "plugin-run"], "run-ok"),
        (["watch", "plugin-watch"], "watch-ok"),
        (["result", "plugin-result"], "result-ok"),
    ):
        assert cli_tools.main(argv) == 0
        assert capsys.readouterr().out.strip() == expected
