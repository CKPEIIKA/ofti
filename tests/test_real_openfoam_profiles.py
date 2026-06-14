from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

import pytest

from ofti.core.case import read_number_of_subdomains
from ofti.core.case_copy import copy_case_directory
from ofti.core.case_snapshot import build_case_snapshot
from ofti.foamlib import runner as foamlib_runner
from ofti.tools import knife_service, parallel_resize_service, process_scan_service, watch_service
from ofti.tools.case_doctor import build_case_doctor_report
from ofti.tools.cli_tools import run, watch
from ofti.tools.runtime_control_service import runtime_control_snapshot
from tests.real_openfoam_support import (
    RealProfile,
    configured_profiles,
    copy_profiles,
    ensure_zero_orig,
    kill_leftovers,
    pid_running,
    prepare_case,
    resolve_solver,
    scenario_enabled,
    wait_pid_running,
    wait_pids_gone,
    write_long_run,
    write_short_run,
    write_simple_decompose_dict,
)


@pytest.fixture(scope="module")
def real_profiles(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[RealProfile, Path]]:
    profiles = configured_profiles()
    if not profiles:
        pytest.skip(
            "Set OFTI_REAL_PROFILES=name=/path/to/case[:compressible=/path] to run real OpenFOAM profiles.",
        )
    return copy_profiles(profiles, tmp_path_factory.mktemp("ofti-real-profiles"))


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
        assert isinstance(jobs["jobs"], list)


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
        assert isinstance(physical["fields"], list)
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
        assert Path(str(compared["reports"]["json"])).is_file()
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
        pid = payload.get("pid")
        try:
            assert isinstance(pid, int), f"{profile.name}: missing started pid"
            if not wait_pid_running(pid, timeout=5.0):
                continue
            stopped = watch.stop_payload(case, job_id=str(payload.get("job_id")), signal_name="TERM")
            assert stopped["selected"] == 1, f"{profile.name}: {stopped}"
            assert stopped["stopped"], f"{profile.name}: {stopped}"
            assert stopped["stopped"][0].get("method") in {"process_group", "processes"}
            assert wait_pids_gone([pid], timeout=5.0), f"{profile.name}: pid still running after stop"
            exercised = True
        finally:
            if isinstance(pid, int) and pid_running(pid):
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
        solver = resolve_solver(profile, case)
        if solver is None:
            continue
        prepare_case(case)
        write_long_run(case, solver)
        write_simple_decompose_dict(case, ranks=2)
        prepared = run.prepare_parallel_case(case, parallel=2, clean_processors=True)
        if prepared.get("decompose_returncode") != 0:
            continue
        try:
            display, command = run.solver_command(case, solver=solver, parallel=2)
        except ValueError:
            continue
        payload = watch_service.start_payload(
            case,
            name=display,
            command=command,
            detached=True,
            log_file=f"log.ofti-stop-{display}",
        )
        pid = payload.get("pid")
        observed_pids: list[int] = [pid] if isinstance(pid, int) else []
        try:
            assert isinstance(pid, int), f"{profile.name}: missing started pid"
            if not wait_pid_running(pid, timeout=5.0):
                continue
            rows = process_scan_service.scan_proc_solver_processes(
                case,
                solver,
                tracked_pids=set(),
                include_tracked=True,
            )
            observed_pids.extend(
                int(row["pid"])
                for row in rows
                if str(row.get("case") or "") == str(case.resolve())
                and isinstance(row.get("pid"), int)
            )
            stopped = watch_service.stop_payload(case, job_id=str(payload.get("job_id")), signal_name="TERM")
            assert stopped["selected"] == 1, f"{profile.name}: {stopped}"
            assert stopped["stopped"], f"{profile.name}: {stopped}"
            assert wait_pids_gone(sorted(set(observed_pids)), timeout=8.0), (
                f"{profile.name}: pids still running after stop: {observed_pids}"
            )
            exercised = True
        finally:
            kill_leftovers(observed_pids)
    if not exercised:
        pytest.skip("No real parallel profile stayed alive long enough for watch stop.")


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
def test_real_queue_records_start_failures_without_blocking_later_cases(
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
        shutil.rmtree(bad_case / "0", ignore_errors=True)
        prepare_case(good_case)
        write_short_run(good_case, solver)
        payload = run.queue_payload(
            cases=[bad_case, good_case],
            solver=solver,
            max_parallel=1,
            backend="process",
        )
        assert payload["ok"] is False, payload
        assert payload["failed_to_start"], payload
        assert len(payload["finished"]) == 1, payload
        assert payload["finished"][0]["returncode"] == 0, payload
        return
    pytest.skip("No real profile with a resolvable serial solver was available.")


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
        assert doctor["lines"]
        assert isinstance(doctor["errors"], list)
        assert isinstance(doctor["warnings"], list)

        preflight = knife_service.preflight_payload(case)
        assert preflight["case"] == str(case)
        assert isinstance(preflight["checks"], dict)

        copied = copy_case_directory(case, tmp_path / f"{profile.name}-clean-copy")
        assert (copied / "system" / "controlDict").is_file()
        assert not (copied / ".ofti").exists()


@pytest.mark.slow
@pytest.mark.real_openfoam
def test_real_parallel_resize_dry_run_profiles(real_profiles: list[tuple[RealProfile, Path]]) -> None:
    if not scenario_enabled("parallel-resize"):
        pytest.skip("parallel-resize real scenario disabled by OFTI_REAL_SCENARIOS")
    for _profile, case in real_profiles:
        decompose_dict = case / "system" / "decomposeParDict"
        if not decompose_dict.is_file():
            continue
        payload = parallel_resize_service.parallel_resize_payload(case, to_ranks=2, dry_run=True)
        assert payload["ok"] is True
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
        decompose_dict = case / "system" / "decomposeParDict"
        if not decompose_dict.is_file():
            continue
        from_ranks = read_number_of_subdomains(decompose_dict)
        if from_ranks is None or from_ranks <= 1:
            continue
        result = run.execute_case_command(case, "decomposePar", ["decomposePar", "-force"], background=False)
        assert result.returncode == 0, f"{profile.name}: {result.stderr or result.stdout}"
        payload = parallel_resize_service.parallel_resize_payload(
            case,
            from_ranks=from_ranks,
            to_ranks=from_ranks,
            start=False,
            write_now=False,
        )
        assert payload["ok"] is True, f"{profile.name}: {payload.get('error')}"
        assert payload["decomposed"] is True
        assert any(row["step"] == "reconstruct" and row["status"] == "done" for row in payload["steps"])
        assert any(row["step"] == "decompose" and row["status"] == "done" for row in payload["steps"])
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
