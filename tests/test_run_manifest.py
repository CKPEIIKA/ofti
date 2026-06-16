from __future__ import annotations

import json
from pathlib import Path

import pytest

from ofti.core import run_manifest, run_receipt
from ofti.core.run_manifest import (
    build_run_manifest,
    resolve_manifest_file,
    restore_run_manifest,
    verify_run_manifest,
    write_case_run_manifest,
)


def _make_case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "constant" / "polyMesh").mkdir(parents=True)
    (path / "0").mkdir(parents=True)
    (path / "system" / "controlDict").write_text("application simpleFoam;\n", encoding="utf-8")
    (path / "system" / "fvSchemes").write_text("ddtSchemes {}\n", encoding="utf-8")
    (path / "constant" / "transportProperties").write_text("nu 1e-05;\n", encoding="utf-8")
    (path / "constant" / "polyMesh" / "boundary").write_text("0\n(\n)\n", encoding="utf-8")
    (path / "0" / "U").write_text("internalField uniform (0 0 0);\n", encoding="utf-8")
    return path


def test_write_manifest_with_recorded_inputs_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)

    manifest_path = write_case_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        record_inputs_copy=True,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_path.is_relative_to(tmp_path / "runs")
    assert payload["manifest_kind"] == "ofti_run_manifest"
    assert payload["inputs"]["recorded_inputs_copy"] is True
    assert payload["inputs"]["inputs_copy_path"] == "inputs"
    assert (manifest_path.parent / "inputs" / "system" / "controlDict").is_file()
    assert any(row["path"] == "system/controlDict" for row in payload["inputs"]["files"])


def test_verify_manifest_detects_changed_and_extra_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    manifest_path = write_case_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
    )

    (case / "system" / "controlDict").write_text("application pisoFoam;\n", encoding="utf-8")
    (case / "system" / "newDict").write_text("x 1;\n", encoding="utf-8")

    payload = verify_run_manifest(manifest_path)
    assert payload["ok"] is False
    assert payload["changed_files"][0]["path"] == "system/controlDict"
    assert payload["extra_files"] == ["system/newDict"]


def test_restore_manifest_requires_recorded_inputs_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    manifest_path = write_case_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
    )

    with pytest.raises(ValueError, match="does not include recorded inputs"):
        restore_run_manifest(manifest_path, tmp_path / "restored")


def test_restore_manifest_copies_case_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    manifest_path = write_case_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        record_inputs_copy=True,
    )

    payload = restore_run_manifest(manifest_path, tmp_path / "restored")

    restored = Path(payload["destination"])
    assert (restored / "system" / "controlDict").read_text(encoding="utf-8").startswith("application")
    assert (restored / ".ofti" / "restored_from_manifest.json").is_file()
    assert payload["selected_roots"] == ["system", "constant", "0"]


def test_restore_manifest_only_selected_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    manifest_path = write_case_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        record_inputs_copy=True,
    )

    payload = restore_run_manifest(
        manifest_path,
        tmp_path / "restored-system",
        only=["system"],
    )

    restored = Path(payload["destination"])
    assert payload["selected_roots"] == ["system"]
    assert (restored / "system" / "controlDict").is_file()
    assert not (restored / "constant").exists()
    assert not (restored / "0").exists()


def test_restore_manifest_skip_selected_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    manifest_path = write_case_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        record_inputs_copy=True,
    )

    payload = restore_run_manifest(
        manifest_path,
        tmp_path / "restored-skip",
        skip=["0"],
    )

    restored = Path(payload["destination"])
    assert payload["selected_roots"] == ["system", "constant"]
    assert (restored / "system" / "controlDict").is_file()
    assert (restored / "constant" / "transportProperties").is_file()
    assert not (restored / "0").exists()


def test_restore_manifest_rejects_empty_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    manifest_path = write_case_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        record_inputs_copy=True,
    )

    with pytest.raises(ValueError, match="selection is empty"):
        restore_run_manifest(
            manifest_path,
            tmp_path / "restored-empty",
            only=["system"],
            skip=["system"],
        )


def test_build_manifest_marks_recorded_inputs_copy_flag(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")

    manifest = build_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=True,
        detached=True,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        recorded_inputs_copy=True,
    )

    assert manifest["launch"]["background"] is True
    assert manifest["inputs"]["recorded_inputs_copy"] is True


def test_run_receipt_compat_aliases_point_to_manifest_api(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")

    manifest = run_receipt.build_run_receipt(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
    )

    assert run_receipt.MANIFEST_KIND == run_manifest.MANIFEST_KIND
    assert run_receipt.DEFAULT_INPUT_ROOTS == run_manifest.DEFAULT_INPUT_ROOTS
    assert manifest["manifest_kind"] == run_manifest.MANIFEST_KIND


def test_build_manifest_records_solver_binary_libs_and_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")

    monkeypatch.setattr(
        run_manifest,
        "_effective_openfoam_env",
        lambda _bashrc: {
            "WM_COMPILER": "Gcc",
            "WM_CXXFLAGS": "-O3",
            "WM_PROJECT_VERSION": "v2212",
        },
    )
    monkeypatch.setattr(
        run_manifest,
        "_solver_binary_row",
        lambda _solver, **_k: {
            "name": "simpleFoam",
            "path": "/opt/of/bin/simpleFoam",
            "sha256": "solver-hash",
            "size": 123,
        },
    )
    monkeypatch.setattr(
        run_manifest,
        "_linked_library_rows",
        lambda _path: {
            "count": 2,
            "hash": "libs-hash",
            "files": [{"path": "/opt/of/lib/libA.so", "sha256": "a", "size": 1}],
            "missing": [],
        },
    )

    manifest = build_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        solver_name="simpleFoam",
    )

    assert manifest["build"]["solver"]["sha256"] == "solver-hash"
    assert manifest["build"]["linked_libs"]["hash"] == "libs-hash"
    assert manifest["build"]["compiler"]["compiler"] == "Gcc"
    assert manifest["build"]["openfoam_env"]["WM_PROJECT_VERSION"] == "v2212"


def test_verify_manifest_reports_build_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        run_manifest,
        "_build_provenance",
        lambda _solver, **_k: {
            "solver": {"name": "simpleFoam", "path": "/x", "sha256": "old-solver", "size": 1},
            "linked_libs": {"count": 1, "hash": "old-libs", "files": [], "missing": []},
            "compiler": {},
            "openfoam_env": {},
        },
    )
    manifest_path = write_case_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        solver_name="simpleFoam",
    )
    monkeypatch.setattr(
        run_manifest,
        "_solver_binary_row",
        lambda _solver, **_k: {
            "name": "simpleFoam",
            "path": "/x",
            "sha256": "new-solver",
            "size": 1,
        },
    )
    monkeypatch.setattr(
        run_manifest,
        "_linked_library_rows",
        lambda _path: {
            "count": 1,
            "hash": "new-libs",
            "files": [],
            "missing": [],
        },
    )

    payload = verify_run_manifest(manifest_path)

    assert payload["ok"] is False
    assert payload["build"]["solver"]["match"] is False
    assert payload["build"]["linked_libs"]["match"] is False


def test_relative_manifest_output_resolves_from_launch_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)

    manifest_path = write_case_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        output=Path("manifests/run-a"),
    )

    assert manifest_path == (launch_dir / "manifests" / "run-a" / "manifest.json").resolve()


def test_verify_manifest_accepts_case_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(case)  # default output -> case/runs/<stamp>/manifest.json

    manifest_path = write_case_run_manifest(
        case,
        name="simpleFoam",
        command="simpleFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
    )
    assert manifest_path.is_relative_to(case / "runs")

    # Passing the case directory must locate the manifest, not raise IsADirectoryError.
    assert resolve_manifest_file(case) == manifest_path
    payload = verify_run_manifest(case)
    assert payload["manifest"] == str(manifest_path)
    assert payload["ok"] is True


def test_resolve_manifest_file_errors_when_directory_has_no_manifest(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no manifest found"):
        resolve_manifest_file(empty)
