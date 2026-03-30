from __future__ import annotations

import os
import types
from pathlib import Path

import pytest

from ofti.tools import solver
from tests.testscreen import TestScreen as _Screen


def _build_case(case: Path) -> None:
    (case / "system").mkdir(parents=True, exist_ok=True)
    (case / "0").mkdir(exist_ok=True)
    (case / "0" / "U").write_text("internalField uniform (0 0 0);\n")
    (case / "0" / "p").write_text("internalField uniform 0;\n")


def test_run_current_solver_guard_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    _build_case(case)
    messages: list[str] = []
    monkeypatch.setattr(solver, "_show_message", lambda _s, text: messages.append(text))

    monkeypatch.setattr(solver, "resolve_solver_name", lambda _case: (None, "bad solver"))
    solver.run_current_solver(_Screen(), case)
    assert "bad solver" in messages[-1]

    monkeypatch.setattr(solver, "resolve_solver_name", lambda _case: (None, None))
    solver.run_current_solver(_Screen(), case)
    assert "Could not determine solver name." in messages[-1]

    monkeypatch.setattr(solver, "resolve_solver_name", lambda _case: ("simpleFoam", None))
    monkeypatch.setattr(solver, "_ensure_zero_dir", lambda *_a, **_k: False)
    called: list[bool] = []
    monkeypatch.setattr(
        solver.run_ops,
        "execute_case_command",
        lambda *_a, **_k: called.append(True),
    )
    solver.run_current_solver(_Screen(), case)
    assert called == []

    monkeypatch.setattr(solver, "_ensure_zero_dir", lambda *_a, **_k: True)
    monkeypatch.setattr(solver, "validate_initial_fields", lambda _case: ["missing 0/U"])
    solver.run_current_solver(_Screen(), case)
    assert "Cannot run solver:" in messages[-1]


def test_run_current_solver_log_prompt_and_execute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    _build_case(case)
    log_path = case / "log.simpleFoam"
    log_path.write_text("old\n")

    monkeypatch.setattr(solver, "resolve_solver_name", lambda _case: ("simpleFoam", None))
    monkeypatch.setattr(solver, "_ensure_zero_dir", lambda *_a, **_k: True)
    monkeypatch.setattr(solver, "validate_initial_fields", lambda _case: [])
    called: list[str] = []

    def _run_solver(*_a: object, **_k: object) -> object:
        called.append("run")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(solver.run_ops, "execute_case_command", _run_solver)
    monkeypatch.setattr(solver, "truncate_log", lambda _path: called.append("truncate"))

    solver.run_current_solver(_Screen(keys=[ord("n")]), case)
    assert called == []

    solver.run_current_solver(_Screen(keys=[ord("y")]), case)
    assert called == ["truncate", "run"]


def test_prepare_parallel_run_and_mpi_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    _build_case(case)
    screen = _Screen()
    messages: list[str] = []
    monkeypatch.setattr(solver, "_show_message", lambda _s, text: messages.append(text))

    monkeypatch.setattr(solver, "resolve_solver_name", lambda _case: (None, "boom"))
    assert solver._prepare_parallel_run(screen, case) is None
    assert "boom" in messages[-1]

    monkeypatch.setattr(solver, "resolve_solver_name", lambda _case: ("simpleFoam", None))
    monkeypatch.setattr(solver, "_ensure_zero_dir", lambda *_a, **_k: False)
    assert solver._prepare_parallel_run(screen, case) is None

    monkeypatch.setattr(solver, "_ensure_zero_dir", lambda *_a, **_k: True)
    monkeypatch.setattr(solver, "validate_initial_fields", lambda _case: ["bad fields"])
    assert solver._prepare_parallel_run(screen, case) is None

    monkeypatch.setattr(solver, "validate_initial_fields", lambda _case: [])
    assert solver._prepare_parallel_run(screen, case) is None
    assert "Missing system/decomposeParDict" in messages[-1]

    (case / "system" / "decomposeParDict").write_text("numberOfSubdomains 0;\n")
    monkeypatch.setattr(solver, "read_number_of_subdomains", lambda _path: 0)
    assert solver._prepare_parallel_run(screen, case) is None
    assert "numberOfSubdomains missing or invalid" in messages[-1]

    monkeypatch.setattr(solver, "read_number_of_subdomains", lambda _path: 4)
    assert solver._prepare_parallel_run(screen, case) == ("simpleFoam", 4)

    monkeypatch.setattr(
        solver,
        "resolve_executable",
        lambda name: (_ for _ in ()).throw(FileNotFoundError("missing")) if name == "mpirun" else "mpiexec",
    )
    assert solver._resolve_mpi_launcher(screen) == "mpiexec"

    monkeypatch.setattr(
        solver,
        "resolve_executable",
        lambda _name: (_ for _ in ()).throw(FileNotFoundError("none")),
    )
    assert solver._resolve_mpi_launcher(screen) is None
    assert "MPI launcher not found" in messages[-1]


def test_run_current_solver_parallel_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "system").mkdir()
    (case / "system" / "decomposeParDict").write_text("numberOfSubdomains 2;\n")
    (case / "log.simpleFoam").write_text("old\n")

    monkeypatch.setattr(solver, "_prepare_parallel_run", lambda *_a, **_k: None)
    calls: list[list[str]] = []
    monkeypatch.setattr(solver, "_run_solver_live_cmd", lambda *_a, **_k: calls.append(list(_a[3])))
    solver.run_current_solver_parallel(_Screen(), case)
    assert calls == []

    monkeypatch.setattr(solver, "_prepare_parallel_run", lambda *_a, **_k: ("simpleFoam", 2))
    monkeypatch.setattr(solver, "remove_empty_log", lambda _path: False)
    solver.run_current_solver_parallel(_Screen(keys=[ord("n")]), case)
    assert calls == []

    monkeypatch.setattr(solver, "truncate_log", lambda _path: None)
    monkeypatch.setattr(solver, "_resolve_mpi_launcher", lambda _s: None)
    solver.run_current_solver_parallel(_Screen(keys=[ord("y")]), case)
    assert calls == []

    monkeypatch.setattr(solver, "_resolve_mpi_launcher", lambda _s: "mpirun")
    solver.run_current_solver_parallel(_Screen(keys=[ord("y")]), case)
    assert calls[-1] == ["mpirun", "-np", "2", "simpleFoam", "-parallel"]


def test_solver_status_helpers_and_clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()

    monkeypatch.setattr(solver, "resolve_solver_name", lambda _case: (None, None))
    assert solver.solver_status_line(case) is None
    assert solver.solver_job_running(case) is False

    summary = types.SimpleNamespace(status="running")
    monkeypatch.setattr(solver, "resolve_solver_name", lambda _case: ("simpleFoam", None))
    monkeypatch.setattr(solver, "latest_solver_job", lambda *_a, **_k: summary)
    monkeypatch.setattr(solver, "solver_status_text", lambda _summary: "simpleFoam running")
    assert solver.solver_status_line(case) == "simpleFoam running"
    assert solver.solver_job_running(case) is True

    summary_finished = types.SimpleNamespace(status="finished")
    monkeypatch.setattr(solver, "latest_solver_job", lambda *_a, **_k: summary_finished)
    assert solver.solver_job_running(case) is False

    monkeypatch.setenv("BASH_ENV", "x")
    monkeypatch.setenv("ENV", "y")
    env = solver._clean_env(case)
    assert "BASH_ENV" not in env
    assert "ENV" not in env
    assert env["PWD"] == str(case.resolve())
    assert env["PATH"] == os.environ["PATH"]
