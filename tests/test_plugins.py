from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ofti.core.command_spec import CommandSpec
from ofti.plugins import (
    FieldPreset,
    PluginRegistry,
    ProfileMatch,
    builtin_registry,
    discover_plugins,
)
from ofti.tools import plugin_service


class FakeProfile:
    name = "fake"

    def detect(self, case_dir: Path) -> ProfileMatch:
        return ProfileMatch(confidence=1.0, reasons=(str(case_dir),))

    def fields(self, case_dir: Path) -> list[str]:
        del case_dir
        return ["rho", "T"]

    def rules(self, case_dir: Path) -> list[str]:
        del case_dir
        return ["rho:min=0", "T:min=0"]


class FakeCommand:
    def __init__(self, name: str) -> None:
        self.name = name

    def command_spec(self) -> CommandSpec:
        return CommandSpec(name=self.name, summary="Fake command", handler=self.run)

    def run(self, args: object) -> int:
        del args
        return 0


class FakeBundleHints:
    name = "fake-bundle"

    def bundle_hints(self, case_dir: Path) -> list[str]:
        return [f"bundle:{case_dir}"]


class FakeProgress:
    name = "fake-progress"

    def progress_metrics(
        self,
        case_dir: Path,
        *,
        log_path: Path | None = None,
    ) -> dict[str, object]:
        return {"case": case_dir.name, "log": str(log_path) if log_path else None}


def test_plugin_registry_accepts_fake_profile_and_preset() -> None:
    registry = builtin_registry()
    registry.add_preset(FieldPreset("fake-flow", ("rho", "T"), source="test"))
    registry.add_physical_profile(FakeProfile())
    registry.add_bundle_hint_provider(FakeBundleHints())
    registry.add_run_command(FakeCommand("run-fake"))
    registry.add_watch_command(FakeCommand("watch-fake"))
    registry.add_result_command(FakeCommand("result-fake"))
    registry.add_progress_metric(FakeProgress())

    assert registry.presets["flow"].source == "core"
    assert registry.presets["fake-flow"].fields == ("rho", "T")
    assert registry.physical_profiles["fake"].rules(Path("case")) == ["rho:min=0", "T:min=0"]
    assert registry.bundle_hints["fake-bundle"].bundle_hints(Path("case")) == ["bundle:case"]
    assert registry.run_commands["run-fake"].name == "run-fake"
    assert registry.watch_commands["watch-fake"].name == "watch-fake"
    assert registry.result_commands["result-fake"].name == "result-fake"
    assert registry.progress_metrics["fake-progress"].progress_metrics(Path("case"))["case"] == "case"


def test_plugin_registry_rejects_duplicate_names_loudly() -> None:
    registry = builtin_registry()

    assert registry.add_knife_command(FakeCommand("charge")) is True
    first = registry.knife_commands["charge"]
    # A second plugin claiming the same command name must not overwrite silently.
    assert registry.add_knife_command(FakeCommand("charge")) is False
    assert registry.knife_commands["charge"] is first
    assert any("duplicate knife command 'charge'" in err for err in registry.errors)

    assert registry.add_preset(FieldPreset("flow", ("p",), source="test")) is False
    assert registry.presets["flow"].source == "core"
    assert registry.add_physical_profile(FakeProfile()) is True
    assert registry.add_physical_profile(FakeProfile()) is False


def test_discovery_records_versions_sources_and_registered_surfaces(monkeypatch) -> None:
    def register(registry: PluginRegistry) -> None:
        registry.add_run_command(FakeCommand("fake-run"))
        registry.add_progress_metric(FakeProgress())

    entry_point = SimpleNamespace(
        name="fake",
        value="fake_plugin:register",
        dist=SimpleNamespace(
            metadata={"Name": "ofti-fake"},
            version="2.4.0",
        ),
        load=lambda: register,
    )
    monkeypatch.setattr("ofti.plugins.entry_points", lambda **_kwargs: [entry_point])

    registry = discover_plugins()
    payload = plugin_service.list_payload(registry)

    assert payload["ok"] is True
    assert payload["plugin_count"] == 1
    assert payload["plugins"][0] == {
        "name": "fake",
        "distribution": "ofti-fake",
        "version": "2.4.0",
        "entry_point": "fake_plugin:register",
        "status": "loaded",
        "registrations": {
            "progress_metrics": ["fake-progress"],
            "run_commands": ["fake-run"],
        },
        "errors": [],
    }


def test_plugin_doctor_reports_load_failure(monkeypatch) -> None:
    def fail() -> object:
        raise RuntimeError("broken import")

    entry_point = SimpleNamespace(
        name="broken",
        value="broken:register",
        dist=None,
        load=fail,
    )
    monkeypatch.setattr("ofti.plugins.entry_points", lambda **_kwargs: [entry_point])

    payload = plugin_service.doctor_payload(discover_plugins())

    assert payload["ok"] is False
    assert payload["failed"] == 1
    assert payload["plugins"][0]["status"] == "failed"
    assert payload["errors"] == ["broken: broken import"]


def test_progress_provider_failure_is_visible_without_hiding_other_metrics(tmp_path: Path) -> None:
    class BrokenProgress:
        name = "broken"

        def progress_metrics(
            self,
            case_dir: Path,
            *,
            log_path: Path | None = None,
        ) -> dict[str, object]:
            del case_dir, log_path
            raise ValueError("bad metric")

    registry = PluginRegistry()
    registry.add_progress_metric(FakeProgress())
    registry.add_progress_metric(BrokenProgress())

    payload = plugin_service.progress_metrics_payload(tmp_path, registry=registry)

    assert payload["metrics"]["fake-progress"]["case"] == tmp_path.name
    assert payload["errors"] == ["broken: bad metric"]
