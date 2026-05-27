from __future__ import annotations

import os
import shlex
import shutil
import signal
import time
from pathlib import Path

import pytest

from ofti.core import entry_io
from ofti.core.case import read_number_of_subdomains
from ofti.core.case_copy import copy_case_directory
from ofti.core.case_snapshot import build_case_snapshot
from ofti.tools import knife_service, parallel_resize_service, watch_service
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
def test_real_background_solver_start_stop_cleans_processes(
    real_profiles: list[tuple[str, Path]],
) -> None:
    exercised = False
    for name, case in real_profiles:
        solver = _solver(case)
        if solver is None:
            continue
        _prepare_real_case(case)
        _write_long_run(case, solver)
        payload = watch_service.start_payload(
            case,
            name=solver,
            command=[solver],
            detached=True,
            log_file=f"log.ofti-stop-{solver}",
        )
        pid = payload.get("pid")
        try:
            assert isinstance(pid, int), f"{name}: missing started pid"
            if not _wait_pid_running(pid, timeout=5.0):
                continue
            stopped = watch.stop_payload(case, job_id=str(payload.get("job_id")), signal_name="TERM")
            assert stopped["selected"] == 1, f"{name}: {stopped}"
            assert stopped["stopped"], f"{name}: {stopped}"
            assert stopped["stopped"][0].get("method") in {"process_group", "processes"}
            assert _wait_pids_gone([pid], timeout=5.0), f"{name}: pid still running after stop"
            exercised = True
        finally:
            if isinstance(pid, int) and _pid_running(pid):
                os.kill(pid, signal.SIGKILL)
    if not exercised:
        pytest.skip("No real profile stayed alive long enough for background stop.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_sequential_queue_runs_cases_and_summarizes_outcomes(
    real_profiles: list[tuple[str, Path]],
    tmp_path: Path,
) -> None:
    for name, source_case in real_profiles:
        solver = _solver(source_case)
        if solver is None:
            continue
        case_a = copy_case_directory(source_case, tmp_path / f"{name}-queue-a")
        case_b = copy_case_directory(source_case, tmp_path / f"{name}-queue-b")
        for case in (case_a, case_b):
            _prepare_real_case(case)
            _write_short_run(case, solver)

        payload = run.queue_payload(
            cases=[case_a, case_b],
            solver=solver,
            max_parallel=1,
            backend="process",
        )

        assert payload["ok"] is True, payload
        assert len(payload["started"]) == 2
        assert len(payload["finished"]) == 2
        for row in payload["finished"]:
            assert row["returncode"] == 0, row
            assert row["outcome"] in {"time", "criteria", "completed"}, row
            assert row["outcome"] != "crashed", row
        return
    pytest.skip("No real profile with a resolvable serial solver was available.")


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
def test_real_parallel_resize_executes_on_stopped_decomposed_profile(
    real_profiles: list[tuple[str, Path]],
) -> None:
    exercised = False
    for name, case in real_profiles:
        decompose_dict = case / "system" / "decomposeParDict"
        if not decompose_dict.is_file():
            continue
        from_ranks = read_number_of_subdomains(decompose_dict)
        if from_ranks is None or from_ranks <= 1:
            continue
        result = run.execute_case_command(
            case,
            "decomposePar",
            ["decomposePar", "-force"],
            background=False,
        )
        assert result.returncode == 0, f"{name}: {result.stderr or result.stdout}"
        payload = parallel_resize_service.parallel_resize_payload(
            case,
            from_ranks=from_ranks,
            to_ranks=from_ranks,
            start=False,
            write_now=False,
        )
        assert payload["ok"] is True, f"{name}: {payload.get('error')}"
        assert payload["decomposed"] is True
        assert any(
            row["step"] == "reconstruct" and row["status"] == "done"
            for row in payload["steps"]
        )
        assert any(
            row["step"] == "decompose" and row["status"] == "done"
            for row in payload["steps"]
        )
        exercised = True
    if not exercised:
        pytest.skip("No real profile with numberOfSubdomains > 1 was available.")


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


def _write_long_run(case: Path, solver: str) -> None:
    control = case / "system" / "controlDict"
    if not control.is_file():
        return
    entry_io.write_entry(control, "application", solver)
    entry_io.write_entry(control, "startFrom", "startTime")
    entry_io.write_entry(control, "startTime", "0")
    entry_io.write_entry(control, "stopAt", "endTime")
    entry_io.write_entry(control, "endTime", os.environ.get("OFTI_REAL_STOP_TEST_END_TIME", "100000"))
    entry_io.write_entry(control, "writeInterval", os.environ.get("OFTI_REAL_STOP_TEST_WRITE_INTERVAL", "100000"))
    time.sleep(0.01)


def _prepare_real_case(case: Path) -> None:
    zero_orig = case / "0.orig"
    zero_dir = case / "0"
    if zero_orig.is_dir() and not zero_dir.exists():
        shutil.copytree(zero_orig, zero_dir)
    poly_mesh = case / "constant" / "polyMesh"
    block_mesh_dict = case / "system" / "blockMeshDict"
    if poly_mesh.is_dir() or not block_mesh_dict.is_file():
        return
    result = run.execute_case_command(
        case,
        "blockMesh",
        ["blockMesh"],
        background=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _pid_running(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    else:
        if ") Z " in stat:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_pid_running(pid: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _pid_running(pid):
            return True
        time.sleep(0.05)
    return False


def _wait_pids_gone(pids: list[int], *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(not _pid_running(pid) for pid in pids):
            return True
        time.sleep(0.05)
    return all(not _pid_running(pid) for pid in pids)
