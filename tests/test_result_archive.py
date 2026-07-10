import json
import tarfile
from pathlib import Path

import pytest

from ofti.core import result_archive
from ofti.tools import result_service


def _case(tmp_path: Path) -> Path:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    (case / "1").mkdir()
    (case / "1" / "U").write_text("result\n")
    (case / "postProcessing" / "forces").mkdir(parents=True)
    (case / "postProcessing" / "forces" / "force.dat").write_text("1 2\n")
    (case / "runs" / "run-1").mkdir(parents=True)
    (case / "runs" / "run-1" / "manifest.json").write_text("{}\n")
    (case / "log.simpleFoam").write_text("End\n")
    return case


def test_result_pack_round_trip_verifies_hashes(tmp_path: Path) -> None:
    case = _case(tmp_path)
    archive = tmp_path / "results.tar.gz"

    packed = result_service.pack_payload(case, archive)
    restored = tmp_path / "restored"
    unpacked = result_service.unpack_payload(archive, restored)

    assert packed["manifest"]["format"] == "ofti.result-pack"
    assert unpacked["manifest"] == packed["manifest"]
    assert (restored / "1" / "U").read_text() == "result\n"
    assert (restored / "postProcessing" / "forces" / "force.dat").is_file()
    assert (restored / "runs" / "run-1" / "manifest.json").is_file()
    assert (restored / "log.simpleFoam").is_file()


def test_result_pack_optionally_includes_processor_state(tmp_path: Path) -> None:
    case = _case(tmp_path)
    for proc in ("processor0", "processor1"):
        (case / proc / "1").mkdir(parents=True)
        (case / proc / "1" / "U").write_text(proc)
        (case / proc / "constant" / "polyMesh").mkdir(parents=True)
        (case / proc / "constant" / "polyMesh" / "points").write_text("mesh")
    archive = tmp_path / "processors.tar.gz"

    manifest = result_archive.create_result_pack(case, archive, include_processors=True)

    names = {row["path"] for row in manifest["files"]}
    assert "processor0/1/U" in names
    assert "processor1/constant/polyMesh/points" in names


def test_result_pack_requires_reconstructed_time_without_processor_option(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case / "1" / "U").unlink()
    (case / "0").mkdir()
    for proc in ("processor0", "processor1"):
        (case / proc / "2").mkdir(parents=True)
        (case / proc / "2" / "U").write_text(proc)

    with pytest.raises(ValueError, match="no reconstructed result time"):
        result_archive.create_result_pack(case, tmp_path / "bad.tar.gz")

    manifest = result_archive.create_result_pack(
        case,
        tmp_path / "state.tar.gz",
        include_processors=True,
    )
    assert manifest["selected_time"] == "2"


def test_result_unpack_rejects_hash_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    manifest = {
        "format": "ofti.result-pack",
        "format_version": 1,
        "selected_time": "1",
        "files": [{"path": "1/U", "size": 3, "sha256": "bad"}],
    }
    with tarfile.open(archive, "w:gz") as tar:
        data = b"bad"
        info = tarfile.TarInfo("1/U")
        info.size = len(data)
        tar.addfile(info, __import__("io").BytesIO(data))
        raw = json.dumps(manifest).encode()
        info = tarfile.TarInfo(result_archive.MANIFEST_PATH)
        info.size = len(raw)
        tar.addfile(info, __import__("io").BytesIO(raw))

    with pytest.raises(ValueError, match="hash mismatch"):
        result_archive.extract_result_pack(archive, tmp_path / "out")
