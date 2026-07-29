from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from ofti.app.cli_tools import main as cli_main
from ofti.core import bundle_set


def _case(root: Path, name: str, application: str = "simpleFoam") -> Path:
    case = root / name
    (case / "system").mkdir(parents=True)
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "0").mkdir()
    (case / "system" / "controlDict").write_text(f"application {application};\n", encoding="utf-8")
    (case / "constant" / "polyMesh" / "points").write_text("points\n", encoding="utf-8")
    (case / "0" / "U").write_text("internalField uniform (0 0 0);\n", encoding="utf-8")
    (case / "log.solver").write_text("excluded\n", encoding="utf-8")
    return case


def test_bundle_set_round_trip_restores_independent_cases(tmp_path: Path) -> None:
    cases = [_case(tmp_path, "coarse"), _case(tmp_path, "fine", "pisoFoam")]
    archive = tmp_path / "study.ofti-set.tar.gz"

    created = bundle_set.create_bundle_set(cases, archive, name="mesh-study")
    restored = tmp_path / "restored"
    extracted = bundle_set.extract_bundle_set(archive, restored)

    assert extracted == created
    assert created.name == "mesh-study"
    assert [entry.name for entry in created.cases] == ["coarse", "fine"]
    assert [entry.manifest.application for entry in created.cases] == ["simpleFoam", "pisoFoam"]
    assert (restored / "coarse" / "system" / "controlDict").is_file()
    assert (restored / "fine" / "constant" / "polyMesh" / "points").is_file()
    assert not (restored / "coarse" / "log.solver").exists()


def test_bundle_set_archive_is_deterministic(tmp_path: Path) -> None:
    cases = [_case(tmp_path, "a"), _case(tmp_path, "b")]
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    bundle_set.create_bundle_set(cases, first, name="same")
    bundle_set.create_bundle_set(cases, second, name="same")

    assert first.read_bytes() == second.read_bytes()


def test_bundle_set_rejects_duplicate_case_names(tmp_path: Path) -> None:
    first = _case(tmp_path / "left", "case")
    second = _case(tmp_path / "right", "case")

    with pytest.raises(ValueError, match="names must be unique"):
        bundle_set.create_bundle_set([first, second], tmp_path / "bad.tar.gz")


def test_bundle_set_rejects_tampered_inner_archive(tmp_path: Path) -> None:
    archive = tmp_path / "study.tar.gz"
    bundle_set.create_bundle_set([_case(tmp_path, "case")], archive)
    manifest = bundle_set.read_bundle_set_manifest(archive)
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(tampered, "w:gz") as tar:
        _add_bytes(tar, manifest.cases[0].archive, b"tampered")
        _add_bytes(tar, bundle_set.MANIFEST_PATH, json.dumps(bundle_set.manifest_payload(manifest)).encode())

    destination = tmp_path / "out"
    with pytest.raises(ValueError, match="verification failed"):
        bundle_set.extract_bundle_set(tampered, destination)
    assert not destination.exists()


def test_bundle_set_rejects_unexpected_members(tmp_path: Path) -> None:
    archive = tmp_path / "study.tar.gz"
    bundle_set.create_bundle_set([_case(tmp_path, "case")], archive)
    manifest = bundle_set.read_bundle_set_manifest(archive)
    unexpected = tmp_path / "unexpected.tar.gz"
    with tarfile.open(unexpected, "w:gz") as tar:
        _add_bytes(tar, "../escape", b"bad")
        _add_bytes(tar, bundle_set.MANIFEST_PATH, json.dumps(bundle_set.manifest_payload(manifest)).encode())

    with pytest.raises(ValueError, match="unexpected bundle-set member"):
        bundle_set.extract_bundle_set(unexpected, tmp_path / "out")


def test_bundle_set_cli_json_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    first = _case(tmp_path, "first")
    second = _case(tmp_path, "second")
    archive = tmp_path / "campaign.tar.gz"

    code = cli_main(["bundle", "set", str(first), str(second), "--output", str(archive), "--json"])
    created = json.loads(capsys.readouterr().out)

    assert code == 0
    assert created["command"] == "bundle set"
    assert created["ok"] is True
    assert len(created["manifest"]["cases"]) == 2

    destination = tmp_path / "campaign"
    code = cli_main(["bundle", "extract", str(archive), "--to", str(destination), "--json"])
    extracted = json.loads(capsys.readouterr().out)

    assert code == 0
    assert extracted["command"] == "bundle extract"
    assert extracted["cases"] == [str((destination / "first").resolve()), str((destination / "second").resolve())]
    assert extracted["next"].startswith("ofti run queue ")


def test_bundle_set_cli_reads_hpc_case_list_from_explicit_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "repo"
    first = _case(root / "runs", "first")
    second = _case(root / "runs", "second")
    cases_file = tmp_path / "cases.txt"
    cases_file.write_text("# prepared campaign\nruns/first\n\nruns/second\n", encoding="utf-8")
    archive = tmp_path / "campaign.tar.gz"

    code = cli_main(
        [
            "bundle",
            "set",
            "--cases-file",
            str(cases_file),
            "--cases-root",
            str(root),
            "--output",
            str(archive),
            "--json",
        ],
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert [row["name"] for row in payload["manifest"]["cases"]] == [first.name, second.name]
    assert archive.is_file()


def test_read_case_list_rejects_empty_input(tmp_path: Path) -> None:
    cases_file = tmp_path / "cases.txt"
    cases_file.write_text("# no cases\n\n", encoding="utf-8")

    with pytest.raises(ValueError, match="case list is empty"):
        bundle_set.read_case_list(cases_file, root=tmp_path)


def test_bundle_extract_rejects_case_only_options_for_sets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = tmp_path / "campaign.tar.gz"
    bundle_set.create_bundle_set([_case(tmp_path, "case")], archive)

    code = cli_main(["bundle", "extract", str(archive), "--to", str(tmp_path / "out"), "--run"])

    assert code == 2
    assert "--run only applies to case bundles" in capsys.readouterr().err


def test_bundle_set_cli_table_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    first = _case(tmp_path, "first")
    second = _case(tmp_path, "second")
    archive = tmp_path / "campaign.tar.gz"

    code = cli_main(["bundle", "set", str(first), str(second), "--output", str(archive), "--table"])
    created = capsys.readouterr().out

    assert code == 0
    assert "Cases" in created
    assert "simpleFoam" in created

    destination = tmp_path / "campaign"
    code = cli_main(["bundle", "extract", str(archive), "--to", str(destination), "--table"])
    extracted = capsys.readouterr().out

    assert code == 0
    assert "cases_verified" in extracted
    assert str((destination / "first").resolve()) in extracted


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))
