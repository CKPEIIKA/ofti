from __future__ import annotations

import os
import shlex
import shutil
import time
from pathlib import Path

import pytest

from ofti.core import entry_io
from ofti.core.case_copy import copy_case_directory
from ofti.core.case_snapshot import build_case_snapshot
from ofti.tools import knife_service, parallel_resize_service
from ofti.tools.case_doctor import build_case_doctor_report
from ofti.tools.cli_tools import run, watch
from ofti.tools.runtime_control_service import runtime_control_snapshot


def _profiles() -> list[tuple[str, Path]]:
    raw = os.environ.get("OFTI_REAL_PROFILES", "").strip()
    if not raw:
        return []
    rows: list[tuple[str, Path]] = []
    for item in raw.split(":"):
        if not item.strip():
            continue
        if "=" in item:
            name, path = item.split("=", 1)
        else:
            path = item
            name = Path(path).name
        case = Path(path).expanduser().resolve()
        if case.is_dir():
            rows.append((name.strip() or case.name, case))
    return rows


@pytest.fixture(scope="module")
def real_profiles(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[str, Path]]:
    profiles = _profiles()
    if not profiles:
        pytest.skip(
            "Set OFTI_REAL_PROFILES=name=/path/to/case[:compressible=/path] to run real OpenFOAM profiles.",
        )
    root = tmp_path_factory.mktemp("ofti-real-profiles")
    copied: list[tuple[str, Path]] = []
    for name, source in profiles:
        destination = root / name
        shutil.copytree(source, destination)
        copied.append((name, destination))
    return copied


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_profiles_runtime_reread_cleanup_and_replay_artifacts(real_profiles: list[tuple[str, Path]]) -> None:
    for name, case in real_profiles:
        solver = _solver(case)
        if solver is None:
            pytest.fail(f"{name}: unable to resolve solver")
        _write_short_run(case, solver)
        result = run.execute_solver_case_command(
            case,
            solver,
            [solver],
            background=False,
        )
        assert result.returncode == 0, result.stderr
        snapshot = runtime_control_snapshot(
            case,
            solver,
            resolve_log_source_fn=lambda source, _solver=solver: source / f"log.{_solver}",
            lightweight=True,
        )
        assert snapshot["log_path"]
        assert snapshot["latest_time"] is not None
        assert snapshot["run_time_control"]["end_time"] is not None
        replay_artifacts = [case / f"log.{solver}", case / ".ofti" / "edits.log"]
        assert any(path.exists() for path in replay_artifacts)
        jobs = watch.jobs_payload(case, include_all=True)
        assert isinstance(jobs["jobs"], list)


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_profiles_core_services_are_fixture_free(
    real_profiles: list[tuple[str, Path]],
    tmp_path: Path,
) -> None:
    for name, case in real_profiles:
        snapshot = build_case_snapshot(case)
        assert snapshot["case"]["path"] == str(case)
        assert "fields" in snapshot

        doctor = build_case_doctor_report(case)
        assert doctor["lines"]
        assert isinstance(doctor["errors"], list)
        assert isinstance(doctor["warnings"], list)

        preflight = knife_service.preflight_payload(case)
        assert preflight["case"] == str(case)
        assert isinstance(preflight["checks"], dict)

        copied = copy_case_directory(case, tmp_path / f"{name}-clean-copy")
        assert (copied / "system" / "controlDict").is_file()
        assert not (copied / ".ofti").exists()


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_parallel_resize_dry_run_profiles(real_profiles: list[tuple[str, Path]]) -> None:
    for _name, case in real_profiles:
        decompose_dict = case / "system" / "decomposeParDict"
        if not decompose_dict.is_file():
            continue
        payload = parallel_resize_service.parallel_resize_payload(case, to_ranks=2, dry_run=True)
        assert payload["ok"] is True
        assert any(row["step"] == "reconstruct" for row in payload["steps"])


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_hpc_profile_smoke_when_available() -> None:
    command = os.environ.get("OFTI_REAL_HPC_COMMAND", "").strip()
    if not command:
        pytest.skip("Set OFTI_REAL_HPC_COMMAND='squeue -h ...' or equivalent for HPC smoke.")
    argv = shlex.split(command)
    assert argv
    assert shutil.which(argv[0]) is not None


def _solver(case: Path) -> str | None:
    try:
        display, command = run.solver_command(case)
    except ValueError:
        return None
    return command[0] if len(command) == 1 else display


def _write_short_run(case: Path, solver: str) -> None:
    control = case / "system" / "controlDict"
    if not control.is_file():
        return
    entry_io.write_entry(control, "application", solver)
    entry_io.write_entry(control, "startFrom", "startTime")
    entry_io.write_entry(control, "startTime", "0")
    entry_io.write_entry(control, "stopAt", "endTime")
    entry_io.write_entry(control, "endTime", os.environ.get("OFTI_REAL_END_TIME", "1"))
    entry_io.write_entry(control, "writeInterval", os.environ.get("OFTI_REAL_WRITE_INTERVAL", "1"))
    time.sleep(0.01)
