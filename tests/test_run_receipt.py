from __future__ import annotations

import json
from pathlib import Path

import pytest

from ofti.core import run_receipt
from ofti.core.run_receipt import (
    build_run_receipt,
    restore_run_receipt,
    verify_run_receipt,
    write_case_run_receipt,
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


def test_write_receipt_with_recorded_inputs_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)

    receipt_path = write_case_run_receipt(
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

    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt_path.is_relative_to(tmp_path / "runs")
    assert payload["receipt_kind"] == "ofti_run_receipt"
    assert payload["inputs"]["recorded_inputs_copy"] is True
    assert payload["inputs"]["inputs_copy_path"] == "inputs"
    assert (receipt_path.parent / "inputs" / "system" / "controlDict").is_file()
    assert any(row["path"] == "system/controlDict" for row in payload["inputs"]["files"])


def test_verify_receipt_detects_changed_and_extra_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    receipt_path = write_case_run_receipt(
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

    payload = verify_run_receipt(receipt_path)
    assert payload["ok"] is False
    assert payload["changed_files"][0]["path"] == "system/controlDict"
    assert payload["extra_files"] == ["system/newDict"]


def test_restore_receipt_requires_recorded_inputs_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    receipt_path = write_case_run_receipt(
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
        restore_run_receipt(receipt_path, tmp_path / "restored")


def test_restore_receipt_copies_case_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    receipt_path = write_case_run_receipt(
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

    payload = restore_run_receipt(receipt_path, tmp_path / "restored")

    restored = Path(payload["destination"])
    assert (restored / "system" / "controlDict").read_text(encoding="utf-8").startswith("application")
    assert (restored / ".ofti" / "restored_from_receipt.json").is_file()
    assert payload["selected_roots"] == ["system", "constant", "0"]


def test_restore_receipt_only_selected_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    receipt_path = write_case_run_receipt(
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

    payload = restore_run_receipt(
        receipt_path,
        tmp_path / "restored-system",
        only=["system"],
    )

    restored = Path(payload["destination"])
    assert payload["selected_roots"] == ["system"]
    assert (restored / "system" / "controlDict").is_file()
    assert not (restored / "constant").exists()
    assert not (restored / "0").exists()


def test_restore_receipt_skip_selected_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    receipt_path = write_case_run_receipt(
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

    payload = restore_run_receipt(
        receipt_path,
        tmp_path / "restored-skip",
        skip=["0"],
    )

    restored = Path(payload["destination"])
    assert payload["selected_roots"] == ["system", "constant"]
    assert (restored / "system" / "controlDict").is_file()
    assert (restored / "constant" / "transportProperties").is_file()
    assert not (restored / "0").exists()


def test_restore_receipt_rejects_empty_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    receipt_path = write_case_run_receipt(
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
        restore_run_receipt(
            receipt_path,
            tmp_path / "restored-empty",
            only=["system"],
            skip=["system"],
        )


def test_build_receipt_marks_recorded_inputs_copy_flag(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")

    receipt = build_run_receipt(
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

    assert receipt["launch"]["background"] is True
    assert receipt["inputs"]["recorded_inputs_copy"] is True


def test_build_receipt_records_solver_binary_libs_and_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")

    monkeypatch.setattr(
        run_receipt,
        "_effective_openfoam_env",
        lambda _bashrc: {
            "WM_COMPILER": "Gcc",
            "WM_CXXFLAGS": "-O3",
            "WM_PROJECT_VERSION": "v2212",
        },
    )
    monkeypatch.setattr(
        run_receipt,
        "_solver_binary_row",
        lambda _solver, **_k: {
            "name": "simpleFoam",
            "path": "/opt/of/bin/simpleFoam",
            "sha256": "solver-hash",
            "size": 123,
        },
    )
    monkeypatch.setattr(
        run_receipt,
        "_linked_library_rows",
        lambda _path: {
            "count": 2,
            "hash": "libs-hash",
            "files": [{"path": "/opt/of/lib/libA.so", "sha256": "a", "size": 1}],
            "missing": [],
        },
    )

    receipt = build_run_receipt(
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

    assert receipt["build"]["solver"]["sha256"] == "solver-hash"
    assert receipt["build"]["linked_libs"]["hash"] == "libs-hash"
    assert receipt["build"]["compiler"]["compiler"] == "Gcc"
    assert receipt["build"]["openfoam_env"]["WM_PROJECT_VERSION"] == "v2212"


def test_verify_receipt_reports_build_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        run_receipt,
        "_build_provenance",
        lambda _solver, **_k: {
            "solver": {"name": "simpleFoam", "path": "/x", "sha256": "old-solver", "size": 1},
            "linked_libs": {"count": 1, "hash": "old-libs", "files": [], "missing": []},
            "compiler": {},
            "openfoam_env": {},
        },
    )
    receipt_path = write_case_run_receipt(
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
        run_receipt,
        "_solver_binary_row",
        lambda _solver, **_k: {
            "name": "simpleFoam",
            "path": "/x",
            "sha256": "new-solver",
            "size": 1,
        },
    )
    monkeypatch.setattr(
        run_receipt,
        "_linked_library_rows",
        lambda _path: {
            "count": 1,
            "hash": "new-libs",
            "files": [],
            "missing": [],
        },
    )

    payload = verify_run_receipt(receipt_path)

    assert payload["ok"] is False
    assert payload["build"]["solver"]["match"] is False
    assert payload["build"]["linked_libs"]["match"] is False


def test_relative_receipt_output_resolves_from_launch_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)

    receipt_path = write_case_run_receipt(
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
        output=Path("receipts/run-a"),
    )

    assert receipt_path == (launch_dir / "receipts" / "run-a" / "receipt.json").resolve()
