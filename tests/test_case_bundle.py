from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from ofti.app.cli_adapters import bundle as bundle_adapter
from ofti.app.cli_tools import main as cli_main
from ofti.core import case_bundle
from ofti.plugins import PluginRegistry
from ofti.tools.runner_service import RunResult


def _case(root: Path) -> Path:
    case = root / "case"
    (case / "system").mkdir(parents=True)
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "0").mkdir(parents=True)
    (case / "processor0" / "0.1").mkdir(parents=True)
    (case / "postProcessing").mkdir()
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    (case / "constant" / "transportProperties").write_text("nu 1e-05;\n")
    (case / "constant" / "polyMesh" / "points").write_text("points\n")
    (case / "0" / "U").write_text("internalField uniform (0 0 0);\n")
    (case / "processor0" / "0.1" / "U").write_text("skip\n")
    (case / "postProcessing" / "probe.dat").write_text("skip\n")
    (case / "log.simpleFoam").write_text("skip\n")
    (case / "Allrun").write_text("#!/bin/sh\n")
    return case


def test_case_bundle_selects_minimal_portable_files(tmp_path: Path) -> None:
    case = _case(tmp_path)
    rels = [path.as_posix() for path in case_bundle.select_bundle_files(case, mesh="exclude")]
    assert rels == [
        "0/U",
        "Allrun",
        "constant/transportProperties",
        "system/controlDict",
    ]


def test_case_bundle_validates_minimal_run_inputs(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()

    with pytest.raises(ValueError, match="system/controlDict"):
        case_bundle.create_bundle(case, tmp_path / "bad.tar.gz")


def test_case_bundle_requires_solver_application(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case / "system" / "controlDict").write_text("startFrom startTime;\n")

    with pytest.raises(ValueError, match="application"):
        case_bundle.create_bundle(case, tmp_path / "bad.tar.gz")


def test_case_bundle_warns_when_mesh_is_excluded(tmp_path: Path) -> None:
    case = _case(tmp_path)
    manifest = case_bundle.build_bundle_manifest(case, mesh="exclude")

    assert manifest.warnings == (
        "mesh excluded; target host must reconstruct or generate mesh before solver run",
    )


def test_case_bundle_includes_local_referenced_include_files(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case / "include").mkdir()
    (case / "include" / "runtime.inc").write_text('#include "nested.inc"\n')
    (case / "include" / "nested.inc").write_text("writeInterval 1;\n")
    (case / "system" / "controlDict").write_text(
        'application simpleFoam;\n#include "../include/runtime.inc"\n',
    )

    rels = [path.as_posix() for path in case_bundle.select_bundle_files(case, mesh="exclude")]

    assert "include/runtime.inc" in rels
    assert "include/nested.inc" in rels


def test_case_bundle_warns_about_missing_referenced_include(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case / "system" / "controlDict").write_text(
        'application simpleFoam;\n#include "../include/missing.inc"\n',
    )

    manifest = case_bundle.build_bundle_manifest(case, mesh="auto")

    assert manifest.warnings == (
        "referenced include not bundled: system/controlDict -> ../include/missing.inc",
    )


def test_case_bundle_warns_about_likely_dictionary_syntax_errors(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case / "system" / "fvSolution").write_text("solvers\n{\n    p GAMG\n}\n")

    manifest = case_bundle.build_bundle_manifest(case, mesh="auto")

    assert any("syntax warning in system/fvSolution" in warning for warning in manifest.warnings)


def test_case_bundle_round_trip_verifies_hashes(tmp_path: Path) -> None:
    case = _case(tmp_path)
    archive = tmp_path / "case.ofti.tar.gz"
    manifest = case_bundle.create_bundle(case, archive, mesh="auto")
    with tarfile.open(archive, "r:*") as tar:
        embedded = tar.extractfile(case_bundle.MANIFEST_PATH)
        assert embedded is not None
        payload = json.loads(embedded.read().decode())
    assert payload["format"] == "ofti.case-bundle"
    assert payload["format_version"] == 1
    out = tmp_path / "out"
    extracted = case_bundle.extract_bundle(archive, out)

    assert extracted == manifest
    assert (out / "system" / "controlDict").read_text() == "application simpleFoam;\n"
    assert (out / "constant" / "polyMesh" / "points").read_text() == "points\n"
    assert not (out / "postProcessing").exists()


def test_case_bundle_archive_is_deterministic(tmp_path: Path) -> None:
    case = _case(tmp_path)
    archive_a = tmp_path / "case-a.ofti.tar.gz"
    archive_b = tmp_path / "case-b.ofti.tar.gz"

    case_bundle.create_bundle(case, archive_a, mesh="auto")
    case_bundle.create_bundle(case, archive_b, mesh="auto")

    assert archive_a.read_bytes() == archive_b.read_bytes()


def test_case_bundle_zstd_archive_requires_safe_backend(tmp_path: Path) -> None:
    case = _case(tmp_path)

    try:
        case_bundle.create_bundle(case, tmp_path / "case.ofti.tar.zst")
    except ValueError as exc:
        assert "zstandard" in str(exc)
    else:
        extracted = case_bundle.extract_bundle(tmp_path / "case.ofti.tar.zst", tmp_path / "out-zst")
        assert extracted.application == "simpleFoam"


def test_case_bundle_rejects_non_empty_destination(tmp_path: Path) -> None:
    case = _case(tmp_path)
    archive = tmp_path / "case.ofti.tar.gz"
    case_bundle.create_bundle(case, archive)
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "existing").write_text("x")

    with pytest.raises(ValueError, match="destination is not empty"):
        case_bundle.extract_bundle(archive, destination)


def test_bundle_cli_json_and_unbundle_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    case = _case(tmp_path)
    archive = tmp_path / "case.ofti.tar.gz"
    code = cli_main(["bundle", str(case), "--output", str(archive), "--json"])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["command"] == "bundle"
    assert output["ok"] is True
    assert output["manifest"]["application"] == "simpleFoam"
    assert output["manifest"]["header_version"] == "unknown"
    assert output["requirements"]["solver"] == "simpleFoam"
    assert output["requirements"]["mesh_included"] is True
    assert output["requirements"]["run_command"] == "ofti run solver CASE --solver simpleFoam"
    assert archive.is_file()

    destination = tmp_path / "unpacked"
    code = cli_main(["unbundle", str(archive), "--to", str(destination), "--json"])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["command"] == "unbundle"
    assert output["ok"] is True
    assert output["requirements"]["solver"] == "simpleFoam"
    assert (destination / "system" / "controlDict").is_file()


def test_bundle_and_unbundle_cli_table_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = _case(tmp_path)
    archive = tmp_path / "case.ofti.tar.gz"

    code = cli_main(["bundle", str(case), "--output", str(archive), "--table"])
    output = capsys.readouterr().out

    assert code == 0
    assert "Key" in output
    assert "archive" in output
    assert "simpleFoam" in output
    assert "Target requirements" in output
    assert "run_command" in output

    destination = tmp_path / "table-unpacked"
    code = cli_main(["unbundle", str(archive), "--to", str(destination), "--table"])
    output = capsys.readouterr().out

    assert code == 0
    assert "files_verified" in output
    assert f"ofti run solver {destination}" in output


def test_bundle_cli_embeds_plugin_bundle_hints(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeHints:
        name = "fake"

        def bundle_hints(self, case_dir: Path) -> tuple[str, ...]:
            return (f"plugin fake: checked {case_dir.name}",)

    case = _case(tmp_path)
    archive = tmp_path / "case.ofti.tar.gz"
    registry = PluginRegistry()
    registry.add_bundle_hint_provider(FakeHints())
    monkeypatch.setattr(bundle_adapter, "discover_plugins", lambda: registry)

    code = cli_main(["bundle", str(case), "--output", str(archive), "--json"])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert "plugin fake: checked case" in output["manifest"]["warnings"]


def test_bundle_cli_smoke_validates_archive_copy(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path)
    archive = tmp_path / "case.ofti.tar.gz"
    smoke_cases: list[Path] = []

    def fake_smoke_payload(case_dir: Path, **kwargs: object) -> dict[str, object]:
        smoke_cases.append(case_dir)
        assert (case_dir / "system" / "controlDict").is_file()
        assert kwargs["in_place"] is True
        assert kwargs["core_only"] is True
        return {
            "ok": True,
            "case": str(case_dir),
            "returncode": 0,
            "log_path": str(case_dir / "log.simpleFoam"),
        }

    monkeypatch.setattr(bundle_adapter.run_ops, "smoke_payload", fake_smoke_payload)

    code = cli_main(["bundle", str(case), "--output", str(archive), "--smoke", "--json"])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["ok"] is True
    assert output["smoke"]["ok"] is True
    assert len(smoke_cases) == 1
    assert archive.is_file()


def test_bundle_cli_smoke_failure_returns_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path)
    archive = tmp_path / "case.ofti.tar.gz"
    monkeypatch.setattr(
        bundle_adapter.run_ops,
        "smoke_payload",
        lambda *_a, **_k: {"ok": False, "returncode": 1, "log_path": "log.simpleFoam"},
    )

    code = cli_main(["bundle", str(case), "--output", str(archive), "--smoke", "--json"])
    output = json.loads(capsys.readouterr().out)

    assert code == 1
    assert output["ok"] is False
    assert output["smoke"]["returncode"] == 1


def test_unbundle_cli_can_run_restored_case(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path)
    archive = tmp_path / "case.ofti.tar.gz"
    case_bundle.create_bundle(case, archive)
    calls: list[Path] = []
    backgrounds: list[bool] = []

    def fake_solver_command(_case_dir: Path, solver: str | None = None) -> tuple[str, list[str]]:
        assert solver is None
        return ("simpleFoam", ["simpleFoam"])

    def fake_dry_run_command(cmd: list[str]) -> str:
        return " ".join(cmd)

    monkeypatch.setattr(
        bundle_adapter.run_ops,
        "solver_command",
        fake_solver_command,
    )
    monkeypatch.setattr(bundle_adapter.run_ops, "dry_run_command", fake_dry_run_command)

    def fake_execute(case_dir: Path, *_args: object, **_kwargs: object) -> RunResult:
        calls.append(case_dir)
        backgrounds.append(bool(_kwargs.get("background")))
        return RunResult(0, "", "", pid=123, log_path=case_dir / "log.simpleFoam")

    monkeypatch.setattr(bundle_adapter.run_ops, "execute_solver_case_command", fake_execute)

    destination = tmp_path / "run-now"
    code = cli_main(
        ["unbundle", str(archive), "--to", str(destination), "--run", "--background", "--json"],
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert calls == [destination]
    assert backgrounds == [True]
    assert output["run"]["returncode"] == 0
    assert output["run"]["command"] == "simpleFoam"
    assert output["run"]["background"] is True
    assert output["run"]["pid"] == 123
    assert Path(output["run"]["manifest"]).is_file()
    assert output["ok"] is True


def test_case_bundle_manifest_is_embedded(tmp_path: Path) -> None:
    case = _case(tmp_path)
    archive = tmp_path / "case.ofti.tar.gz"
    case_bundle.create_bundle(case, archive)

    with tarfile.open(archive, "r:gz") as tar:
        names = sorted(member.name for member in tar.getmembers())

    assert case_bundle.MANIFEST_PATH in names
    assert "processor0/0.1/U" not in names
    assert "log.simpleFoam" not in names
