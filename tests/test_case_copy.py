from __future__ import annotations

from pathlib import Path

import pytest

from ofti.core.case_copy import copy_case_directory


def _make_case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "system" / "controlDict").write_text("application simpleFoam;\n")
    (path / "0").mkdir()
    (path / "0" / "U").write_text("uniform (0 0 0)\n")
    return path


def test_copy_case_default_skips_runtime_artifacts(tmp_path: Path) -> None:
    source = _make_case(tmp_path / "source")
    (source / "1").mkdir()
    (source / "1" / "U").write_text("runtime\n")
    (source / "log.simpleFoam").write_text("log\n")
    (source / "processor0").mkdir()
    (source / "processor0" / "U").write_text("runtime\n")
    (source / "postProcessing").mkdir()
    (source / "postProcessing" / "probe.dat").write_text("1\n")
    (source / ".ofti").mkdir()
    (source / ".ofti" / "jobs.json").write_text("[]\n")
    (source / "constant" / "polyMesh").mkdir(parents=True)
    (source / "constant" / "polyMesh" / "boundary").write_text("boundary\n")
    (source / "source.foam").write_text("\n")

    dest = copy_case_directory(source, tmp_path / "copied")

    assert dest.is_dir()
    assert (dest / "0" / "U").is_file()
    assert (dest / "constant" / "polyMesh" / "boundary").is_file()
    assert not (dest / "1").exists()
    assert not (dest / "log.simpleFoam").exists()
    assert not (dest / "processor0").exists()
    assert not (dest / "postProcessing").exists()
    assert not (dest / ".ofti").exists()
    assert not (dest / "source.foam").exists()


def test_copy_case_with_runtime_and_drop_mesh_options(tmp_path: Path) -> None:
    source = _make_case(tmp_path / "source")
    (source / "1").mkdir()
    (source / "1" / "U").write_text("runtime\n")
    (source / "constant" / "polyMesh").mkdir(parents=True)
    (source / "constant" / "polyMesh" / "boundary").write_text("boundary\n")

    with_runtime = copy_case_directory(
        source,
        tmp_path / "with_runtime",
        include_runtime_artifacts=True,
    )
    assert (with_runtime / "1" / "U").is_file()
    assert (with_runtime / "constant" / "polyMesh" / "boundary").is_file()

    drop_mesh = copy_case_directory(
        source,
        tmp_path / "drop_mesh",
        include_runtime_artifacts=True,
        drop_mesh=True,
    )
    assert not (drop_mesh / "constant" / "polyMesh").exists()


def test_copy_case_validates_source_and_destination(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source case directory not found"):
        copy_case_directory(tmp_path / "missing", tmp_path / "dest")

    not_case = tmp_path / "not_case"
    not_case.mkdir()
    with pytest.raises(ValueError, match="missing system/controlDict"):
        copy_case_directory(not_case, tmp_path / "dest")

    source = _make_case(tmp_path / "source")
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ValueError, match="destination already exists"):
        copy_case_directory(source, dest)

    nested = source / "copied"
    with pytest.raises(ValueError, match="outside source case"):
        copy_case_directory(source, nested)
