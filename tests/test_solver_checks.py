from __future__ import annotations

from pathlib import Path

from ofti.core.solver_checks import (
    remove_empty_log,
    resolve_solver_name,
    truncate_log,
    validate_initial_fields,
)


def test_resolve_solver_name_reads_control_dict(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    system_dir = case_dir / "system"
    system_dir.mkdir(parents=True)
    (system_dir / "controlDict").write_text("application simpleFoam;\n")

    monkeypatch.setattr("ofti.core.solver_checks.read_entry", lambda *_a, **_k: "simpleFoam;")
    solver, error = resolve_solver_name(case_dir)

    assert error is None
    assert solver == "simpleFoam"


def test_validate_initial_fields_missing_zero(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    errors = validate_initial_fields(case_dir)

    assert errors
    assert "Missing 0/ initial conditions directory." in errors[0]


def test_validate_initial_fields_missing_required_field(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    zero_dir = case_dir / "0"
    zero_dir.mkdir(parents=True)
    (zero_dir / "U").write_text("internalField uniform (0 0 0);\n")

    errors = validate_initial_fields(case_dir)

    assert errors
    assert "Missing fields" in errors[0]


def test_remove_empty_log(tmp_path: Path) -> None:
    log_path = tmp_path / "log.simpleFoam"
    log_path.write_text("")

    assert remove_empty_log(log_path) is True
    assert not log_path.exists()


def test_truncate_log(tmp_path: Path) -> None:
    log_path = tmp_path / "log.simpleFoam"
    log_path.write_text("content\n")

    truncate_log(log_path)

    assert log_path.read_text() == ""
