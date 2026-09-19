from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from ofti.core.case import read_number_of_subdomains
from ofti.core.case_copy import copy_case_directory
from ofti.core.case_snapshot import build_case_snapshot
from ofti.foamlib import runner as foamlib_runner
from ofti.tools import (
    checkpoint_service,
    knife_service,
    parallel_resize_service,
    process_scan_service,
    result_service,
    watch_service,
)
from ofti.tools.case_doctor import build_case_doctor_report
from ofti.tools.cli_tools import run, run_queue, watch
from ofti.tools.runtime_control_service import runtime_control_snapshot
from tests.real_openfoam_support import (
    RealProfile,
    configured_profiles,
    copy_profiles,
    ensure_zero_orig,
    kill_leftovers,
    mpi_launcher_issue,
    pid_running,
    prepare_case,
    resolve_solver,
    scenario_enabled,
    wait_pid_running,
    wait_pids_gone,
    write_long_run,
    write_scotch_decompose_dict,
    write_short_run,
    write_simple_decompose_dict,
)
from tests.real_openfoam_tutorials import make_tutorial_case, selected_tutorial_profiles, wait_until


@pytest.fixture
def real_profiles(tmp_path: Path) -> Iterator[list[tuple[RealProfile, Path]]]:
    profiles = configured_profiles()
    if profiles:
        yield copy_profiles(profiles, tmp_path / "external")
        return
    generated = []
    for profile in selected_tutorial_profiles():
        root = tmp_path / profile.name
        root.mkdir()
        generated.append(make_tutorial_case(profile, root))
    try:
        yield [
            (
                RealProfile(
                    name=item.profile.name,
                    source=item.case,
                    solver=item.profile.required_commands[0],
                    tags=frozenset({"generated", "parallel"}),
                ),
                item.case,
            )
            for item in generated
        ]
    finally:
        for item in generated:
            item.cleanup()


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_profiles_runtime_reread_cleanup_and_replay_artifacts(
    real_profiles: list[tuple[RealProfile, Path]],
) -> None:
    if not scenario_enabled("runtime"):
        pytest.skip("runtime real scenario disabled by OFTI_REAL_SCENARIOS")
    for profile, case in real_profiles:
        solver = resolve_solver(profile, case)
        if solver is None:
            pytest.fail(f"{profile.name}: unable to resolve solver")
        write_short_run(case, solver)
        result = run.execute_solver_case_command(case, solver, [solver], background=False)
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
        assert jobs["count"] == len(jobs["jobs"])
        assert all(str(job.get("status")) != "running" for job in jobs["jobs"])


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_profiles_smoke_command_runs_bounded_copy(
    real_profiles: list[tuple[RealProfile, Path]],
    tmp_path: Path,
) -> None:
    if not scenario_enabled("smoke"):
        pytest.skip("smoke real scenario disabled by OFTI_REAL_SCENARIOS")
    for profile, case in real_profiles:
        solver = resolve_solver(profile, case)
        if solver is None:
            pytest.fail(f"{profile.name}: unable to resolve solver")
        prepare_case(case)
        payload = run.smoke_payload(
            case,
            solver=solver,
            iterations=int(os.environ.get("OFTI_REAL_SMOKE_ITERATIONS", "1")),
            timeout=float(os.environ.get("OFTI_REAL_SMOKE_TIMEOUT", "60")),
            output_root=tmp_path / f"smoke-{profile.name}",
            run_physical=True,
        )
        assert payload["ok"] is True, payload
        assert payload["copied"] is True
        assert Path(str(payload["log_path"])).is_file()
        assert Path(str(payload["output_root"]), "summary.json").is_file()
        assert "physical" in payload


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_physical_and_compare_fields_use_real_time_dirs(
    real_profiles: list[tuple[RealProfile, Path]],
    tmp_path: Path,
) -> None:
    if not scenario_enabled("diagnostics"):
        pytest.skip("diagnostics real scenario disabled by OFTI_REAL_SCENARIOS")
    for profile, source_case in real_profiles:
        case_a = copy_case_directory(source_case, tmp_path / f"{profile.name}-diag-a")
        case_b = copy_case_directory(source_case, tmp_path / f"{profile.name}-diag-b")
        physical = knife_service.physical_payload(case_a, time_name="latest")
        assert physical["case"] == str(case_a)
        assert physical["field_count"] == len(physical["fields"])
        if not physical["fields"]:
            continue
        field_names = [str(row["field"]) for row in physical["fields"][:3]]
        compared = knife_service.compare_fields_payload(
            case_a,
            case_b,
            fields=field_names,
            time_name="latest",
            out_dir=tmp_path / f"{profile.name}-compare",
        )
        assert compared["ok"] is True, compared
        assert compared["fields"]
        assert Path(str(compared["outputs"]["csv"])).is_file()
        return
    pytest.skip("No real profile exposed readable latest-time fields.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_background_solver_start_stop_cleans_processes(
    real_profiles: list[tuple[RealProfile, Path]],
) -> None:
    if not scenario_enabled("start-stop"):
        pytest.skip("start-stop real scenario disabled by OFTI_REAL_SCENARIOS")
    exercised = False
    for profile, case in real_profiles:
        solver = resolve_solver(profile, case)
        if solver is None:
            continue
        prepare_case(case)
        write_long_run(case, solver)
        payload = watch_service.start_payload(
            case,
            name=solver,
            command=[solver],
            detached=True,
            log_file=f"log.ofti-stop-{solver}",
        )
        pid_raw = payload.get("pid")
        pid = int(pid_raw) if pid_raw is not None else 0
        try:
            assert pid > 0, f"{profile.name}: missing started pid"
            if not wait_pid_running(pid, timeout=5.0):
                continue
            stopped = watch.stop_payload(case, job_id=str(payload.get("job_id")), signal_name="TERM")
            assert stopped["selected"] == 1, f"{profile.name}: {stopped}"
            assert stopped["stopped"], f"{profile.name}: {stopped}"
            assert stopped["stopped"][0].get("method") in {"process_group", "processes"}
            assert wait_pids_gone([pid], timeout=5.0), f"{profile.name}: pid still running after stop"
            exercised = True
        finally:
            if pid > 0 and pid_running(pid):
                kill_leftovers([pid])
    if not exercised:
        pytest.skip("No real profile stayed alive long enough for background stop.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_parallel_watch_stop_cleans_launcher_and_solver_ranks(
    real_profiles: list[tuple[RealProfile, Path]],
) -> None:
    if not scenario_enabled("parallel-stop"):
        pytest.skip("parallel-stop real scenario disabled by OFTI_REAL_SCENARIOS")
    if shutil.which("decomposePar") is None:
        pytest.skip("parallel watch stop requires OpenFOAM decomposePar on PATH.")
    exercised = False
    for profile, case in real_profiles:
        exercised = _exercise_parallel_tracked_stop(profile, case) or exercised
    if not exercised:
        pytest.skip("No profile had a usable MPI launcher and long-running parallel solver.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_parallel_raw_launcher_adopt_groups_and_stops_one_run(
    real_profiles: list[tuple[RealProfile, Path]],
) -> None:
    if not scenario_enabled("parallel-adopt"):
        pytest.skip("parallel-adopt real scenario disabled by OFTI_REAL_SCENARIOS")
    exercised = any(_exercise_parallel_raw_adopt(profile, case) for profile, case in real_profiles)
    if not exercised:
        pytest.skip("No profile had a usable MPI launcher and adoptable parallel solver.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_decomposed_checkpoint_and_direct_field_compare(
    real_profiles: list[tuple[RealProfile, Path]],
    tmp_path: Path,
) -> None:
    if not scenario_enabled("parallel-compare"):
        pytest.skip("parallel-compare real scenario disabled by OFTI_REAL_SCENARIOS")
    for profile, source_case in real_profiles:
        serial = copy_case_directory(source_case, tmp_path / f"{profile.name}-serial-fields")
        decomposed = copy_case_directory(source_case, tmp_path / f"{profile.name}-decomposed-fields")
        prepare_case(serial)
        prepare_case(decomposed)
        write_simple_decompose_dict(decomposed, ranks=2)
        prepared = run.prepare_parallel_case(decomposed, parallel=2, clean_processors=True)
        if prepared.get("decompose_returncode") != 0:
            continue
        checkpoint = checkpoint_service.checkpoint_payload(decomposed, expected_processors=2)
        assert checkpoint["latest_complete_time"] == "0", checkpoint
        physical = knife_service.physical_payload(serial, time_name="0")
        fields = [str(row["field"]) for row in physical["fields"] if row.get("ok")][:3]
        if not fields:
            continue
        shutil.rmtree(decomposed / "0")
        compared = knife_service.compare_fields_payload(serial, decomposed, fields=fields)
        assert compared["ok"] is True, compared
        assert compared["time_policy"] == "latest-common"
        assert compared["mesh"]["same"] is True
        assert all(row["max_abs"] == 0 for row in compared["fields"])
        return
    pytest.skip("No real profile exposed comparable decomposed initial fields.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_decomposed_result_pack_preserves_complete_processor_state(
    real_profiles: list[tuple[RealProfile, Path]],
    tmp_path: Path,
) -> None:
    if not scenario_enabled("parallel-compare"):
        pytest.skip("parallel-compare real scenario disabled by OFTI_REAL_SCENARIOS")
    for profile, source_case in real_profiles:
        case = copy_case_directory(source_case, tmp_path / f"{profile.name}-result-pack")
        prepare_case(case)
        write_simple_decompose_dict(case, ranks=2)
        prepared = run.prepare_parallel_case(case, parallel=2, clean_processors=True)
        if prepared.get("decompose_returncode") != 0:
            continue
        checkpoint = checkpoint_service.checkpoint_payload(case, expected_processors=2)
        if checkpoint["latest_complete_time"] != "0":
            continue

        archive = tmp_path / f"{profile.name}-processor-state.tar.gz"
        packed = result_service.pack_payload(
            case,
            archive,
            time_name="0",
            include_processors=True,
        )
        restored = tmp_path / f"{profile.name}-processor-state"
        unpacked = result_service.unpack_payload(archive, restored)

        assert unpacked["manifest"] == packed["manifest"]
        assert packed["manifest"]["include_processors"] is True
        assert any((restored / "processor0" / "0").iterdir())
        assert any((restored / "processor1" / "0").iterdir())
        assert (restored / "processor0" / "constant" / "polyMesh").is_dir()
        return
    pytest.skip("No real profile exposed a complete decomposed initial state.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_sequential_queue_runs_cases_and_summarizes_outcomes(
    real_profiles: list[tuple[RealProfile, Path]],
    tmp_path: Path,
) -> None:
    if not scenario_enabled("queue"):
        pytest.skip("queue real scenario disabled by OFTI_REAL_SCENARIOS")
    for profile, source_case in real_profiles:
        solver = resolve_solver(profile, source_case)
        if solver is None:
            continue
        case_a = copy_case_directory(source_case, tmp_path / f"{profile.name}-queue-a")
        case_b = copy_case_directory(source_case, tmp_path / f"{profile.name}-queue-b")
        for case in (case_a, case_b):
            prepare_case(case)
            write_short_run(case, solver)

        payload = run.queue_payload(cases=[case_a, case_b], solver=solver, max_parallel=1, backend="process")

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
def test_real_queue_records_crashes_without_blocking_later_cases(
    real_profiles: list[tuple[RealProfile, Path]],
    tmp_path: Path,
) -> None:
    if not scenario_enabled("queue-failure"):
        pytest.skip("queue-failure real scenario disabled by OFTI_REAL_SCENARIOS")
    for profile, source_case in real_profiles:
        solver = resolve_solver(profile, source_case)
        if solver is None:
            continue
        bad_case = copy_case_directory(source_case, tmp_path / f"{profile.name}-queue-bad")
        good_case = copy_case_directory(source_case, tmp_path / f"{profile.name}-queue-good")
        transport = bad_case / "constant" / "transportProperties"
        if not transport.is_file():
            continue
        transport.unlink()
        prepare_case(bad_case)
        write_short_run(bad_case, solver)
        prepare_case(good_case)
        write_short_run(good_case, solver)
        payload = run.queue_payload(
            cases=[bad_case, good_case],
            solver=solver,
            max_parallel=1,
            backend="process",
        )
        assert payload["ok"] is False, payload
        assert payload["failed_to_start"] == [], payload
        assert len(payload["finished"]) == 2, payload
        assert payload["finished"][0]["outcome"] == "crashed", payload
        assert payload["finished"][1]["returncode"] == 0, payload
        assert watch_service.jobs_payload(bad_case, include_all=False, kind="solver")["count"] == 0
        assert watch_service.jobs_payload(good_case, include_all=False, kind="solver")["count"] == 0
        return
    pytest.skip("No real profile with a resolvable serial solver was available.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_queue_criterion_evidence_and_crash_cleanup(
    real_profiles: list[tuple[RealProfile, Path]],
    tmp_path: Path,
) -> None:
    if not scenario_enabled("queue-criteria"):
        pytest.skip("queue-criteria real scenario disabled by OFTI_REAL_SCENARIOS")
    for profile, source_case in real_profiles:
        solver = resolve_solver(profile, source_case)
        if solver is None:
            continue
        case = copy_case_directory(source_case, tmp_path / f"{profile.name}-queue-criteria")
        prepare_case(case)
        write_short_run(case, solver)
        queued = run.queue_payload(cases=[case], solver=solver, max_parallel=1, backend="process")
        if not queued["finished"] or queued["finished"][0]["returncode"] != 0:
            continue
        knife_service.set_entry_payload(case, "system/controlDict", "endTime", "1e30")
        knife_service.set_entry_payload(case, "system/controlDict", "residualTolerance", "1e30")
        log_path = max(case.glob("log.*"), key=lambda path: path.stat().st_mtime)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("\nrunTimeControl: residualTolerance satisfied\n")
        status = run.status_row_payload(case, lightweight=True, tail_bytes=256 * 1024)
        row = run_queue.queue_finished_row(status, case=str(case), pid=None, returncode=0)
        assert row["outcome"] == "criteria", row
        assert watch_service.jobs_payload(case, include_all=False, kind="solver")["count"] == 0
        assert not process_scan_service.scan_proc_solver_processes(
            case,
            solver,
            tracked_pids=set(),
            include_tracked=True,
        )
        return
    pytest.skip("No real profile completed a queue run for criterion classification.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_foamlib_case_ops_blockmesh_restore_and_reconstruct(
    real_profiles: list[tuple[RealProfile, Path]],
    tmp_path: Path,
) -> None:
    if not scenario_enabled("foamlib-ops"):
        pytest.skip("foamlib-ops real scenario disabled by OFTI_REAL_SCENARIOS")
    if shutil.which("blockMesh") is None:
        pytest.skip("foamlib case-op execution requires OpenFOAM tools on PATH.")
    for profile, source_case in real_profiles:
        case = copy_case_directory(source_case, tmp_path / f"{profile.name}-foamlib-ops")
        solver = resolve_solver(profile, case)
        if solver is None:
            continue
        ensure_zero_orig(case)

        shutil.rmtree(case / "0", ignore_errors=True)
        foamlib_runner.restore_0_dir(case)
        assert (case / "0").is_dir()

        shutil.rmtree(case / "constant" / "polyMesh", ignore_errors=True)
        prepare_case(case)
        assert (case / "constant" / "polyMesh").is_dir()

        write_short_run(case, solver)
        write_simple_decompose_dict(case, ranks=2)
        prepared = run.prepare_parallel_case(case, parallel=2, clean_processors=True)
        assert prepared["decompose_returncode"] == 0, prepared
        assert (case / "processor0").is_dir()
        display, command = run.solver_command(case, solver=solver, parallel=2)
        if mpi_launcher_issue(command):
            continue
        result = run.execute_solver_case_command(case, display, command, parallel=2, background=False)
        assert result.returncode == 0, result.stderr
        foamlib_runner.reconstruct_case(case, check=True, log="log.reconstructPar")
        assert (case / "log.reconstructPar").is_file()
        return
    pytest.skip("No real profile was available for foamlib case-op coverage.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_profiles_core_services_are_fixture_free(
    real_profiles: list[tuple[RealProfile, Path]],
    tmp_path: Path,
) -> None:
    if not scenario_enabled("core-services"):
        pytest.skip("core-services real scenario disabled by OFTI_REAL_SCENARIOS")
    for profile, case in real_profiles:
        snapshot = build_case_snapshot(case)
        assert snapshot["case"]["path"] == str(case)
        assert "fields" in snapshot

        doctor = build_case_doctor_report(case)
        assert doctor["lines"][0] == "CASE DOCTOR"
        assert f"Path: {case}" in doctor["lines"]
        assert all(str(message).strip() for message in [*doctor["errors"], *doctor["warnings"]])

        preflight = knife_service.preflight_payload(case)
        assert preflight["case"] == str(case)
        assert preflight["checks"]
        assert preflight["checks"]["system/controlDict"] is True
        assert preflight["checks"]["solver_entry"] is True

        copied = copy_case_directory(case, tmp_path / f"{profile.name}-clean-copy")
        assert (copied / "system" / "controlDict").is_file()
        assert not (copied / ".ofti").exists()


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_parallel_resize_dry_run_profiles(real_profiles: list[tuple[RealProfile, Path]]) -> None:
    if not scenario_enabled("parallel-resize"):
        pytest.skip("parallel-resize real scenario disabled by OFTI_REAL_SCENARIOS")
    for profile, case in real_profiles:
        prepare_case(case)
        write_scotch_decompose_dict(case, ranks=2)
        result = run.execute_case_command(case, "decomposePar", ["decomposePar", "-force"], background=False)
        assert result.returncode == 0, f"{profile.name}: {result.stderr or result.stdout}"
        payload = parallel_resize_service.parallel_resize_payload(case, to_ranks=2, dry_run=True)
        assert payload["ok"] is True
        assert payload["restart_plan"]["safe_to_apply"] is True
        assert any(row["step"] == "reconstruct" for row in payload["steps"])


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_parallel_resize_executes_on_stopped_decomposed_profile(
    real_profiles: list[tuple[RealProfile, Path]],
) -> None:
    if not scenario_enabled("parallel-resize-exec"):
        pytest.skip("parallel-resize-exec real scenario disabled by OFTI_REAL_SCENARIOS")
    exercised = False
    for profile, case in real_profiles:
        prepare_case(case)
        from_ranks = 2
        to_ranks = int(os.environ.get("OFTI_REAL_RESIZE_TO", "3"))
        if to_ranks <= 1 or to_ranks == from_ranks:
            pytest.fail("OFTI_REAL_RESIZE_TO must be >1 and different from 2")
        write_scotch_decompose_dict(case, ranks=from_ranks)
        result = run.execute_case_command(case, "decomposePar", ["decomposePar", "-force"], background=False)
        assert result.returncode == 0, f"{profile.name}: {result.stderr or result.stdout}"
        payload = parallel_resize_service.parallel_resize_payload(
            case,
            from_ranks=from_ranks,
            to_ranks=to_ranks,
            start=False,
            write_now=False,
        )
        assert payload["ok"] is True, f"{profile.name}: {payload.get('error')}"
        assert payload["decomposed"] is True
        assert any(row["step"] == "reconstruct" and row["status"] == "done" for row in payload["steps"])
        assert any(row["step"] == "decompose" and row["status"] == "done" for row in payload["steps"])
        assert read_number_of_subdomains(case / "system" / "decomposeParDict") == to_ranks
        assert len(list(case.glob("processor[0-9]*"))) == to_ranks
        exercised = True
    if not exercised:
        pytest.skip("No real profile with numberOfSubdomains > 1 was available.")


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_hpc_profile_smoke_when_available() -> None:
    if not scenario_enabled("hpc"):
        pytest.skip("hpc real scenario disabled by OFTI_REAL_SCENARIOS")
    command = os.environ.get("OFTI_REAL_HPC_COMMAND", "").strip()
    if not command:
        pytest.skip("Set OFTI_REAL_HPC_COMMAND='squeue -h ...' or equivalent for HPC smoke.")
    argv = shlex.split(command)
    assert argv
    assert shutil.which(argv[0]) is not None


def _parallel_command(profile: RealProfile, case: Path) -> tuple[str, str, list[str]] | None:
    solver = resolve_solver(profile, case)
    if solver is None:
        return None
    prepare_case(case)
    write_long_run(case, solver)
    write_simple_decompose_dict(case, ranks=2)
    prepared = run.prepare_parallel_case(case, parallel=2, clean_processors=True)
    if prepared.get("decompose_returncode") != 0:
        return None
    try:
        display, command = run.solver_command(case, solver=solver, parallel=2)
    except ValueError:
        return None
    return None if mpi_launcher_issue(command) else (solver, display, command)


def _exercise_parallel_tracked_stop(profile: RealProfile, case: Path) -> bool:
    prepared = _parallel_command(profile, case)
    if prepared is None:
        return False
    solver, display, command = prepared
    payload = watch_service.start_payload(
        case,
        name=display,
        command=command,
        detached=True,
        log_file=f"log.ofti-stop-{display}",
    )
    pid = payload.get("pid")
    observed = [pid] if isinstance(pid, int) else []
    try:
        if not isinstance(pid, int) or not wait_pid_running(pid, timeout=5.0):
            return False
        rows = process_scan_service.scan_proc_solver_processes(
            case,
            solver,
            tracked_pids=set(),
            include_tracked=True,
        )
        observed.extend(int(row["pid"]) for row in rows if isinstance(row.get("pid"), int))
        stopped = watch_service.stop_payload(
            case,
            job_id=str(payload.get("job_id")),
            signal_name="TERM",
        )
        assert stopped["selected"] == 1, f"{profile.name}: {stopped}"
        assert wait_pids_gone(sorted(set(observed)), timeout=8.0)
        return True
    finally:
        kill_leftovers(observed)


def _exercise_parallel_raw_adopt(profile: RealProfile, case: Path) -> bool:
    prepared = _parallel_command(profile, case)
    if prepared is None:
        return False
    _solver, display, command = prepared
    log_path = case / f"log.raw-adopt-{display}"
    with log_path.open("a", encoding="utf-8") as log:
        # The test command is assembled from the controlled profile fixture.
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=case,
            stdout=log,
            stderr=log,
            text=True,
            start_new_session=True,
        )
    observed = [process.pid]
    try:
        if not wait_pid_running(process.pid, timeout=5.0):
            return False
        wait_until(
            lambda: bool(
                process_scan_service.scan_proc_solver_processes(
                    case,
                    None,
                    tracked_pids=set(),
                ),
            ),
            timeout=8.0,
            description=f"{profile.name} raw MPI process discovery",
        )
        adopted = knife_service.adopt_payload(case)
        assert adopted["failed"] == [], f"{profile.name}: {adopted}"
        assert len(adopted["adopted"]) == 1, f"{profile.name}: {adopted}"
        row = adopted["adopted"][0]
        assert row["role"] == "launcher"
        assert row["solver_pids"]
        observed.extend(int(pid) for pid in row["solver_pids"])
        stopped = watch_service.stop_payload(case, all_jobs=True, kind="solver")
        assert stopped["selected"] == 1, f"{profile.name}: {stopped}"
        assert wait_pids_gone(sorted(set(observed)), timeout=8.0)
        return True
    finally:
        kill_leftovers(observed)
