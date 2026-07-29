from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from ofti.app.cli_tools import main as cli_main
from ofti.core import bundle_set, case_bundle, entry_io, field_io, run_manifest
from ofti.foam.times import latest_time
from ofti.tools import (
    checkpoint_service,
    dictionary_transaction_service,
    knife_service,
    parallel_resize_service,
    result_service,
    runtime_control_service,
    sample_metric_service,
    watch_service,
)
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.cli_tools import run_queue
from tests.real_openfoam_tutorials import (
    RealTutorialCase,
    TutorialProfile,
    make_tutorial_case,
    running_jobs,
    selected_tutorial_profiles,
    wait_until,
)

pytestmark = [pytest.mark.slow, pytest.mark.real_openfoam]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "tutorial_profile" not in metafunc.fixturenames:
        return
    profiles = selected_tutorial_profiles()
    metafunc.parametrize("tutorial_profile", profiles, ids=[profile.name for profile in profiles])


@pytest.fixture
def real_case(tutorial_profile: TutorialProfile, tmp_path: Path) -> Iterator[RealTutorialCase]:
    case = make_tutorial_case(tutorial_profile, tmp_path)
    try:
        yield case
    finally:
        case.cleanup()


def _require_cavity_profile(real_case: RealTutorialCase) -> None:
    if real_case.profile.name != "icoFoam-cavity":
        pytest.skip("binary field contract currently uses the canonical cavity profile")


def _configure_binary_single_step(case: Path) -> None:
    settings = {
        "startFrom": "startTime",
        "startTime": "0",
        "endTime": "0.005",
        "writeInterval": "1",
        "writeFormat": "binary",
    }
    for key, value in settings.items():
        assert knife_service.set_entry_payload(case, "system/controlDict", key, value)["ok"] is True


def test_real_toy_case_prelaunch_diagnostics_and_manifest(real_case: RealTutorialCase, tmp_path: Path) -> None:
    case = real_case.case
    assert knife_service.preflight_payload(case)["ok"] is True
    assert knife_service.initials_payload(case)["field_count"] >= 1

    physical = knife_service.physical_payload(case, time_name="latest")
    assert physical["case"] == str(case)

    display, command = run_ops.solver_command(case)
    manifest = run_ops.dry_run_command(command)
    manifest_path = tmp_path / "manifest.json"

    written = run_manifest.write_case_run_manifest(
        case,
        name=display,
        command=manifest,
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        output=manifest_path,
        record_inputs_copy=True,
    )
    assert written == manifest_path.resolve()
    assert run_manifest.verify_run_manifest(written, case_path=case)["ok"] is True


def test_real_toy_case_transactional_dictionary_edit(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    case = real_case.case

    preview = dictionary_transaction_service.set_entries_payload(
        case,
        [
            ("system/controlDict", "endTime", "0.01"),
            ("system/controlDict", "writeInterval", "1"),
        ],
        apply=False,
    )
    applied = dictionary_transaction_service.set_entries_payload(
        case,
        [
            ("system/controlDict", "endTime", "0.01"),
            ("system/controlDict", "writeInterval", "1"),
        ],
    )

    assert preview["applied"] is False
    assert applied["ok"] is True, applied
    assert applied["applied"] is True
    assert Path(str(applied["snapshot"]), "snapshot.json").is_file()
    assert Path(str(applied["manifest"])).is_file()
    assert "endTime 0.01;" in Path(case, "system", "controlDict").read_text(encoding="utf-8")
    smoke = run_ops.smoke_payload(
        case,
        iterations=2,
        timeout=60,
        output_root=tmp_path / "transaction-smoke",
        core_only=True,
    )
    assert smoke["ok"] is True, smoke
    assert smoke["output_readable"] is True


def test_real_toy_case_foamlib_control_round_trip_remains_runnable(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    case = real_case.case
    control = case / "system" / "controlDict"

    assert entry_io.write_entry(control, "writeInterval", "2") is True
    assert float(entry_io.read_entry(control, "writeInterval").rstrip(";")) == 2

    smoke = run_ops.smoke_payload(
        case,
        iterations=2,
        timeout=60,
        output_root=tmp_path / "foamlib-round-trip-smoke",
        core_only=True,
    )
    assert smoke["ok"] is True, smoke
    assert smoke["iterations_completed"] == 2
    assert smoke["checkpoint_ok"] is True


def test_real_toy_case_binary_scalar_and_vector_fields_are_physical(real_case: RealTutorialCase) -> None:
    _require_cavity_profile(real_case)
    case = real_case.case
    _configure_binary_single_step(case)
    display, command = run_ops.solver_command(case)
    real_case.run_tool(display, command)

    time_name = latest_time(case)
    pressure = field_io.read_internal_field(case / time_name / "p")
    velocity = field_io.read_internal_field(case / time_name / "U")
    physical = knife_service.physical_payload(case, time_name="latest", fields=["p", "U"])
    pressure_mean = sample_metric_service.field_metric_payload(case, "p", reduction="mean")
    velocity_max = sample_metric_service.field_metric_payload(case, "U", reduction="max")
    moving_wall = sample_metric_service.field_metric_payload(
        case,
        "U",
        time_name="0",
        patch="movingWall",
        reduction="max",
    )

    assert pressure.count == 400
    assert pressure.declared_count == 400
    assert velocity.count == 400
    assert velocity.component_count == 3
    assert physical["hard_errors"] == []
    assert pressure_mean["finite_count"] == 400
    assert cast("float", pressure_mean["min"]) <= cast("float", pressure_mean["value"])
    assert cast("float", pressure_mean["value"]) <= cast("float", pressure_mean["max"])
    assert velocity_max["finite_count"] == 400
    assert cast("float", velocity_max["value"]) >= 0.0
    assert moving_wall["value"] == pytest.approx(1.0)


def test_real_toy_case_decomposed_binary_fields_reduce_across_ranks(real_case: RealTutorialCase) -> None:
    _require_cavity_profile(real_case)
    case = real_case.case
    _configure_binary_single_step(case)
    display, command = run_ops.solver_command(case)
    real_case.run_tool(display, command)
    time_name = latest_time(case)
    real_case.ensure_parallel_dict(2)
    real_case.run_tool("decomposePar", ["decomposePar", "-force", "-latestTime"])
    (case / time_name).rename(case / ".serial-binary-result")

    time_dir = field_io.resolve_time_dir(case, "latest")
    pressure = field_io.read_field_values(time_dir / "p")
    velocity = field_io.read_field_values(time_dir / "U")
    physical = knife_service.physical_payload(case, time_name="latest", fields=["p", "U"])

    assert pressure.count == 400
    assert velocity.count == 400
    assert velocity.component_count == 3
    assert physical["hard_errors"] == []


def test_real_toy_case_cli_manifest_write_is_case_local_and_verifiable(
    real_case: RealTutorialCase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = real_case.case

    code = cli_main(["knife", "manifest", "write", str(case), "--json"])
    written = json.loads(capsys.readouterr().out)

    assert code == 0
    manifest_path = Path(str(written["manifest"]))
    assert manifest_path.is_relative_to(case / "runs")
    assert manifest_path.is_file()

    code = cli_main(["knife", "manifest", "verify", str(case), "--json"])
    verified = json.loads(capsys.readouterr().out)

    assert code == 0
    assert verified["ok"] is True
    assert verified["manifest"] == str(manifest_path)


def test_real_toy_case_run_manifest_restore_is_runnable(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    case = real_case.case
    display, command = run_ops.solver_command(case)
    manifest_path = tmp_path / "restore-manifest.json"
    written = run_manifest.write_case_run_manifest(
        case,
        name=display,
        command=run_ops.dry_run_command(command),
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        output=manifest_path,
        record_inputs_copy=True,
    )
    restored = tmp_path / "manifest-restored"

    payload = run_manifest.restore_run_manifest(written, restored)

    assert payload["ok"] is True
    assert set(payload["restored"]) >= {"system", "constant", "0"}
    assert (restored / "system" / "controlDict").is_file()
    assert knife_service.preflight_payload(restored)["ok"] is True
    status = knife_service.status_payload(restored, lightweight=True)
    assert status["case"] == str(restored)
    assert status["solver"] == display


def test_real_toy_case_manifest_restore_executes_solver(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    case = real_case.case
    display, command = run_ops.solver_command(case)
    manifest_path = run_manifest.write_case_run_manifest(
        case,
        name=display,
        command=run_ops.dry_run_command(command),
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        output=tmp_path / "executable-restore-manifest.json",
        record_inputs_copy=True,
    )
    restored = tmp_path / "executable-manifest-restore"
    run_manifest.restore_run_manifest(manifest_path, restored)

    smoke = run_ops.smoke_payload(
        restored,
        solver=display,
        iterations=2,
        timeout=60,
        output_root=restored,
        in_place=True,
        core_only=True,
    )

    assert smoke["ok"] is True, smoke
    assert Path(str(smoke["log_path"])).is_file()
    assert latest_time(restored) != "0"


def test_real_toy_case_bundle_extract_status(real_case: RealTutorialCase, tmp_path: Path) -> None:
    case = real_case.case
    display, command = run_ops.solver_command(case)
    external_manifest = run_manifest.write_case_run_manifest(
        case,
        name=display,
        command=run_ops.dry_run_command(command),
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        output=tmp_path / "external-run-manifest.json",
    )
    archive = tmp_path / "real-case.ofti.tar.gz"
    manifest = case_bundle.create_bundle(
        case,
        archive,
        mesh="auto",
        time="0",
        run_manifest=external_manifest,
    )
    restored = tmp_path / "restored"
    extracted = case_bundle.extract_bundle(archive, restored)

    assert extracted == manifest
    assert manifest.run_manifest == case_bundle.BUNDLED_RUN_MANIFEST_PATH
    assert (restored / case_bundle.BUNDLED_RUN_MANIFEST_PATH).is_file()
    assert (restored / "system" / "controlDict").is_file()
    assert (restored / "constant" / "polyMesh").is_dir()
    assert not (restored / "postProcessing").exists()
    assert knife_service.preflight_payload(restored)["ok"] is True
    assert knife_service.status_payload(restored, lightweight=True)["case"] == str(restored)


def test_real_toy_case_extracted_smoke_run_is_watchable(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    case = real_case.case
    archive = tmp_path / "real-case-smoke.ofti.tar.gz"
    case_bundle.create_bundle(case, archive, mesh="auto", time="0")
    restored = tmp_path / "restored-smoke"
    case_bundle.extract_bundle(archive, restored)

    smoke = run_ops.smoke_payload(
        restored,
        iterations=2,
        timeout=60,
        output_root=restored,
        in_place=True,
        core_only=True,
    )
    status = knife_service.status_payload(restored, lightweight=True, tail_bytes=256 * 1024)

    assert smoke["ok"] is True
    assert Path(str(smoke["log_path"])).is_file()
    assert status["case"] == str(restored)
    assert status["log_path"] == smoke["log_path"]
    assert status["latest_time"] is not None
    assert "reason_codes" in status["progress"]


def test_real_toy_case_bundle_set_restores_and_runs_every_case(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    source = real_case.case
    cases = [tmp_path / "bundle-set-a", tmp_path / "bundle-set-b"]
    for case in cases:
        shutil.copytree(source, case)
    archive = tmp_path / "real-study.ofti-set.tar.gz"
    created = bundle_set.create_bundle_set(cases, archive, name="real-study", mesh="auto", time="0")
    restored = tmp_path / "restored-study"

    extracted = bundle_set.extract_bundle_set(archive, restored)

    assert extracted == created
    for entry in extracted.cases:
        case = restored / entry.name
        smoke = run_ops.smoke_payload(
            case,
            iterations=2,
            timeout=60,
            output_root=case,
            in_place=True,
            core_only=True,
        )
        assert smoke["ok"] is True, smoke
        assert smoke["iterations_completed"] == 2
        assert smoke["checkpoint_ok"] is True


def test_real_toy_case_smoke_forces_exact_steps_from_adaptive_source(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    case = real_case.case
    assert knife_service.set_entry_payload(case, "system/controlDict", "adjustTimeStep", "yes")["ok"] is True

    smoke = run_ops.smoke_payload(
        case,
        iterations=5,
        timeout=60,
        output_root=tmp_path / "adaptive-source-smoke",
        core_only=True,
    )

    assert smoke["ok"] is True, smoke
    assert smoke["iterations_completed"] == 5
    assert smoke["iteration_count_exact"] is True
    assert smoke["requested_iterations_reached"] is True
    assert smoke["target_time_reached"] is True
    assert smoke["checkpoint_ok"] is True
    assert smoke["latest_written_time"] != "0"
    control_text = Path(str(smoke["case"]), "system", "controlDict").read_text(encoding="utf-8")
    assert any(f"adjustTimeStep {value};" in control_text for value in ("false", "no"))


def test_real_toy_case_parallel_smoke_writes_common_final_checkpoint(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    if not real_case.profile.supports_parallel:
        pytest.skip(f"{real_case.profile.name} does not support parallel scenario")
    if shutil.which("mpirun") is None and shutil.which("mpiexec") is None:
        pytest.skip("MPI launcher unavailable")
    case = real_case.case
    real_case.ensure_parallel_dict(2)
    _require_working_parallel_launcher(run_ops.solver_command(case, parallel=2)[1])

    smoke = run_ops.smoke_payload(
        case,
        iterations=5,
        timeout=90,
        parallel=2,
        output_root=tmp_path / "parallel-exact-smoke",
        core_only=True,
        clean_processors=True,
        reconstruct=True,
    )

    assert smoke["ok"] is True, smoke
    assert smoke["iterations_completed"] == 5
    assert smoke["checkpoint_ok"] is True
    assert smoke["latest_complete_processor_time"] == smoke["latest_written_time"]
    assert smoke["checkpoint"]["processor_count"] == 2
    assert smoke["checkpoint"]["partial_times"] == []
    assert smoke["output_readable"] is True
    assert smoke["reconstruction_ok"] is True
    assert smoke["reconstruction"]["returncode"] == 0


def test_real_toy_case_smoke_result_pack_round_trip(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    case = real_case.case
    smoke = run_ops.smoke_payload(
        case,
        iterations=2,
        timeout=60,
        output_root=case,
        in_place=True,
        core_only=True,
    )
    assert smoke["ok"] is True, smoke
    archive = tmp_path / "real-results.tar.gz"

    packed = result_service.pack_payload(case, archive)
    restored = tmp_path / "real-results"
    unpacked = result_service.unpack_payload(archive, restored)

    selected = str(packed["manifest"]["selected_time"])
    assert unpacked["manifest"] == packed["manifest"]
    assert (restored / selected).is_dir()
    assert any(restored.glob("log.*"))


def test_real_toy_case_bundle_cli_smoke_is_portable(
    real_case: RealTutorialCase,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = real_case.case
    archive = tmp_path / "real-case-cli-smoke.ofti.tar.gz"

    code = cli_main(
        [
            "bundle",
            "case",
            str(case),
            "--output",
            str(archive),
            "--time",
            "0",
            "--mesh",
            "auto",
            "--smoke",
            "--smoke-iterations",
            "2",
            "--smoke-timeout",
            "60s",
            "--json",
        ],
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert archive.is_file()
    assert payload["ok"] is True
    assert payload["manifest"]["files"]
    assert payload["smoke"]["ok"] is True
    assert Path(str(payload["smoke"].get("case_dir") or payload["smoke"]["case"])).is_dir()
    assert Path(str(payload["smoke"]["log_path"])).is_file()


def test_real_toy_case_tracked_start_status_and_stop(real_case: RealTutorialCase) -> None:
    case = real_case.case
    pid = real_case.start_solver()
    assert pid > 0
    wait_until(lambda: running_jobs(case) >= 1, description="tracked solver discovery")

    current = knife_service.current_payload(case, live=True)
    assert int(current["jobs_running"]) >= 1
    assert watch_service.jobs_payload(case, include_all=False, kind="solver")["count"] >= 1

    status = knife_service.status_payload(case, lightweight=True, tail_bytes=256 * 1024)
    assert status["solver"]
    assert int(status["jobs_running"]) >= 1

    stopped = real_case.stop_all_solvers()
    assert stopped["selected"] >= 1
    wait_until(lambda: running_jobs(case) == 0, description="stopped solver")
    all_jobs = watch_service.jobs_payload(case, include_all=True, kind="solver")
    assert all(str(job.get("status")) != "running" for job in all_jobs["jobs"])


def test_real_toy_case_cli_watch_start_jobs_stop_contract(
    real_case: RealTutorialCase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = real_case.case
    solver, _command = run_ops.solver_command(case)
    assert knife_service.set_entry_payload(case, "system/controlDict", "endTime", "1e30")["ok"] is True

    started_code = cli_main(["watch", "start", str(case), "--solver", solver, "--json"])
    started = json.loads(capsys.readouterr().out)
    pid = int(started["pid"])
    try:
        assert started_code == 0
        assert pid > 0
        assert Path(str(started["log_path"])).is_file()
        wait_until(lambda: running_jobs(case) == 1, description="CLI-started solver registry")

        jobs_code = cli_main(["watch", "jobs", str(case), "--kind", "solver", "--json"])
        jobs = json.loads(capsys.readouterr().out)
        assert jobs_code == 0
        assert jobs["count"] == 1
        assert int(jobs["jobs"][0]["pid"]) == pid
        assert jobs["jobs"][0]["status"] == "running"

        stop_code = cli_main(["watch", "stop", str(case), "--all", "--kind", "solver", "--json"])
        stopped = json.loads(capsys.readouterr().out)
        assert stop_code == 0
        assert stopped["selected"] == 1
        assert stopped["failed"] == []
        wait_until(lambda: running_jobs(case) == 0, description="CLI-stopped solver registry")
    finally:
        real_case.stop_all_solvers()


def test_real_toy_case_start_pause_resume_restart_and_jobs(real_case: RealTutorialCase) -> None:
    case = real_case.case
    pid = real_case.start_solver()
    assert pid > 0
    try:
        wait_until(lambda: running_jobs(case) >= 1, description="initial tracked solver")
        jobs = watch_service.jobs_payload(case, include_all=False, kind="solver")
        assert jobs["count"] >= 1
        assert all(str(job.get("kind")) == "solver" for job in jobs["jobs"])

        paused = watch_service.pause_payload(case, all_jobs=True, kind="solver")
        assert paused["selected"] >= 1
        assert paused["failed"] == []
        assert paused["paused"]

        resumed = watch_service.resume_payload(case, all_jobs=True, kind="solver")
        assert resumed["selected"] >= 1
        assert resumed["failed"] == []
        assert resumed["resumed"]
    finally:
        real_case.stop_all_solvers()
    wait_until(lambda: running_jobs(case) == 0, description="stopped before restart")

    restarted_pid = real_case.start_solver()
    assert restarted_pid > 0
    try:
        wait_until(lambda: running_jobs(case) >= 1, description="restarted tracked solver")
        restarted = watch_service.jobs_payload(case, include_all=False, kind="solver")
        assert restarted["count"] >= 1
        assert int(knife_service.current_payload(case, live=True)["jobs_running"]) >= 1
    finally:
        real_case.stop_all_solvers()
    wait_until(lambda: running_jobs(case) == 0, description="stopped restarted solver")


def test_real_toy_case_progress_tracks_live_pause_and_resume(real_case: RealTutorialCase) -> None:
    case = real_case.case
    pid = real_case.start_solver()
    assert pid > 0
    try:
        wait_until(lambda: running_jobs(case) >= 1, description="progress-state solver")
        live = watch_service.jobs_payload(case, include_all=False, kind="solver")["progress"]
        assert live["process_live"] is True
        assert live["paused"] is False
        assert "IDLE" not in live["reason_codes"]
        assert live["state"] in {"STARTING", "SOLVING", "WRITING"}

        paused = watch_service.pause_payload(case, all_jobs=True, kind="solver")
        assert paused["failed"] == []
        progress = watch_service.jobs_payload(case, include_all=False, kind="solver")["progress"]
        assert progress["process_live"] is False
        assert progress["paused"] is True
        assert progress["reason_codes"] == ["PAUSED"]
        assert progress["state"] == "STALLED_LOG"

        resumed = watch_service.resume_payload(case, all_jobs=True, kind="solver")
        assert resumed["failed"] == []
        progress = watch_service.jobs_payload(case, include_all=False, kind="solver")["progress"]
        assert progress["process_live"] is True
        assert progress["paused"] is False
        assert "PAUSED" not in progress["reason_codes"]
    finally:
        real_case.stop_all_solvers()
    wait_until(lambda: running_jobs(case) == 0, description="progress-state solver stopped")


def test_real_toy_case_dead_tracked_process_recovers_to_finished(real_case: RealTutorialCase) -> None:
    case = real_case.case
    pid = real_case.start_solver()
    assert pid > 0
    wait_until(lambda: running_jobs(case) >= 1, description="tracked solver discovery before kill")
    try:
        os.kill(pid, 15)
        wait_until(lambda: running_jobs(case) == 0, timeout=12.0, description="dead tracked solver recovery")
        jobs = watch_service.jobs_payload(case, include_all=True, kind="solver")
        assert jobs["jobs"]
        assert all(str(job.get("status")) != "running" for job in jobs["jobs"])
    finally:
        real_case.stop_all_solvers()


def test_real_toy_case_adopts_untracked_solver_and_stops_it(real_case: RealTutorialCase) -> None:
    case = real_case.case
    display, command = run_ops.solver_command(case)
    log_path = case / f"log.raw-{display}"
    with log_path.open("a", encoding="utf-8", errors="ignore") as log:
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=case,
            stdout=log,
            stderr=log,
            text=True,
            start_new_session=True,
        )
    try:
        wait_until(lambda: _untracked_solver_count(case) >= 1, description="raw solver discovery")

        adopted = knife_service.adopt_payload(case)

        assert adopted["failed"] == []
        assert len(adopted["adopted"]) >= 1
        wait_until(lambda: running_jobs(case) >= 1, description="adopted solver registry")
        jobs = watch_service.jobs_payload(case, include_all=False, kind="solver")
        assert jobs["count"] >= 1
        assert any(int(job.get("pid") or 0) == process.pid for job in jobs["jobs"])
    finally:
        stopped = real_case.stop_all_solvers()
        if stopped["selected"] < 1 and process.poll() is None:
            process.terminate()
        wait_until(lambda: running_jobs(case) == 0, description="adopted solver stopped")


def test_real_toy_case_adopts_raw_parallel_mpirun_as_one_tracked_run(
    real_case: RealTutorialCase,
) -> None:
    if not real_case.profile.supports_parallel:
        pytest.skip(f"{real_case.profile.name} does not support parallel scenario")
    if shutil.which("mpirun") is None and shutil.which("mpiexec") is None:
        pytest.skip("MPI launcher unavailable")

    case = real_case.case
    real_case.ensure_parallel_dict(2)
    prepared = run_ops.prepare_parallel_case(case, parallel=2, clean_processors=True)
    assert prepared["decompose_returncode"] == 0
    display, command = run_ops.solver_command(case, parallel=2)
    _require_working_parallel_launcher(command)
    log_path = case / f"log.raw-{display}"
    with log_path.open("a", encoding="utf-8", errors="ignore") as log:
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=case,
            stdout=log,
            stderr=log,
            text=True,
            start_new_session=True,
        )
    try:
        wait_until(lambda: _untracked_solver_count(case) >= 1, description="raw mpirun discovery")

        adopted = knife_service.adopt_payload(case)

        assert adopted["failed"] == []
        assert len(adopted["adopted"]) == 1
        row = adopted["adopted"][0]
        assert row["role"] == "launcher"
        assert int(row["pid"]) == process.pid
        assert row["solver_pids"]
        wait_until(lambda: running_jobs(case) >= 1, description="adopted mpirun registry")
        jobs = watch_service.jobs_payload(case, include_all=False, kind="solver")
        assert jobs["count"] == 1
        job = jobs["jobs"][0]
        assert int(job.get("launcher_pid") or 0) == process.pid
        assert job.get("solver_pids")
    finally:
        stopped = real_case.stop_all_solvers()
        if stopped["selected"] < 1 and process.poll() is None:
            process.terminate()
        wait_until(lambda: running_jobs(case) == 0, description="adopted mpirun stopped")


def test_real_toy_case_runtime_write_now_snapshot_stops_solver(real_case: RealTutorialCase) -> None:
    case = real_case.case
    pid = real_case.start_solver()
    assert pid > 0
    wait_until(lambda: running_jobs(case) >= 1, description="runtime writeNow solver discovery")

    payload = runtime_control_service.control_dict_edit_payload(
        case,
        {"stopAt": "writeNow"},
        write_snapshot=True,
        apply=True,
    )

    assert payload["ok"] is True
    assert payload["applied"] is True
    assert payload["snapshot_path"]
    assert "stopAt writeNow;" in (case / "system" / "controlDict").read_text()
    try:
        wait_until(lambda: running_jobs(case) == 0, timeout=8.0, description="writeNow stopped solver")
    except AssertionError:
        stopped = real_case.stop_all_solvers()
        assert stopped["selected"] >= 1
        wait_until(lambda: running_jobs(case) == 0, description="fallback stopped solver")
    status = knife_service.status_payload(case, lightweight=True, tail_bytes=256 * 1024)
    assert status["latest_time"] is not None


def test_real_toy_case_sequential_queue_reports_terminal_outcomes(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    source = real_case.case
    solver, _command = run_ops.solver_command(source)
    case_a = tmp_path / "queue-a"
    case_b = tmp_path / "queue-b"
    shutil.copytree(source, case_a)
    shutil.copytree(source, case_b)
    for case in (case_a, case_b):
        assert knife_service.set_entry_payload(case, "system/controlDict", "endTime", "0.005")["ok"] is True
        assert knife_service.set_entry_payload(case, "system/controlDict", "writeInterval", "1")["ok"] is True
        assert knife_service.set_entry_payload(case, "system/controlDict", "purgeWrite", "2")["ok"] is True

    payload = run_ops.queue_payload(
        cases=[case_a, case_b],
        solver=solver,
        max_parallel=1,
        backend="process",
        poll_interval=0.1,
        queue_root=tmp_path,
    )

    assert payload["ok"] is True, payload
    assert Path(str(payload["queue_path"])).is_file()
    assert len(payload["started"]) == 2
    assert len(payload["finished"]) == 2
    outcomes = {str(row["outcome"]) for row in payload["finished"]}
    assert outcomes <= {"time", "criteria", "completed"}
    assert "crashed" not in outcomes
    assert payload["summary"]["outcomes"]
    by_events = run_ops.queue_summary_payload(Path(str(payload["queue_events_path"])))
    by_record = run_ops.queue_summary_payload(Path(str(payload["queue_path"])))
    assert by_events["summary"]["finished"] == 2
    assert by_record["summary"]["finished"] == 2
    assert by_events["summary"]["outcomes"] == payload["summary"]["outcomes"]


def test_real_toy_case_queue_continues_after_crashed_case(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    source = real_case.case
    solver, _command = run_ops.solver_command(source)
    bad_case = tmp_path / "queue-bad"
    good_case = tmp_path / "queue-good"
    shutil.copytree(source, bad_case)
    shutil.copytree(source, good_case)
    (bad_case / "constant" / "transportProperties").unlink()
    for case in (bad_case, good_case):
        assert knife_service.set_entry_payload(case, "system/controlDict", "endTime", "0.005")["ok"] is True
        assert knife_service.set_entry_payload(case, "system/controlDict", "writeInterval", "1")["ok"] is True
        assert knife_service.set_entry_payload(case, "system/controlDict", "purgeWrite", "2")["ok"] is True

    payload = run_ops.queue_payload(
        cases=[bad_case, good_case],
        solver=solver,
        max_parallel=1,
        backend="process",
        poll_interval=0.1,
        queue_root=tmp_path,
    )

    assert payload["ok"] is False, payload
    assert payload["failed_to_start"] == []
    assert len(payload["started"]) == 2
    assert len(payload["finished"]) == 2
    assert payload["finished"][0]["outcome"] == "crashed"
    assert payload["finished"][0]["returncode"] != 0
    assert payload["finished"][1]["returncode"] == 0
    assert payload["finished"][1]["outcome"] in {"time", "criteria", "completed"}
    assert payload["summary"]["outcomes"]["crashed"] == 1
    assert watch_service.jobs_payload(bad_case, include_all=False, kind="solver")["count"] == 0
    assert watch_service.jobs_payload(good_case, include_all=False, kind="solver")["count"] == 0
    assert running_jobs(bad_case) == 0
    assert running_jobs(good_case) == 0


def test_real_toy_case_queue_classifier_uses_explicit_criterion_evidence(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    case = real_case.case
    solver, _command = run_ops.solver_command(case)
    assert knife_service.set_entry_payload(case, "system/controlDict", "endTime", "0.005")["ok"]
    queued = run_ops.queue_payload(
        cases=[case],
        solver=solver,
        max_parallel=1,
        backend="process",
        poll_interval=0.1,
        queue_root=tmp_path,
    )
    assert queued["finished"][0]["returncode"] == 0
    assert knife_service.set_entry_payload(case, "system/controlDict", "endTime", "1000")["ok"]
    assert knife_service.set_entry_payload(
        case,
        "system/controlDict",
        "residualTolerance",
        "1e9",
    )["ok"]
    log_path = max(case.glob("log.*"), key=lambda path: path.stat().st_mtime)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\nrunTimeControl: residualTolerance satisfied\n")

    status = run_ops.status_row_payload(case, lightweight=True, tail_bytes=256 * 1024)
    classified = run_queue.queue_finished_row(
        status,
        case=str(case),
        pid=None,
        returncode=0,
    )

    assert status["criteria_passed"] >= 1
    assert classified["outcome"] == "criteria"
    assert classified["stop_reason"] == "criteria_met"


def test_real_toy_case_criteria_reads_explicit_runtime_evidence(real_case: RealTutorialCase) -> None:
    case = real_case.case
    solver, _command = run_ops.solver_command(case)
    assert knife_service.set_entry_payload(case, "system/controlDict", "residualTolerance", "1e-1")["ok"] is True
    smoke = run_ops.smoke_payload(
        case,
        solver=solver,
        iterations=2,
        timeout=60,
        output_root=case,
        in_place=True,
        core_only=True,
    )
    assert smoke["ok"] is True, smoke
    log_path = Path(str(smoke["log_path"]))
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\nrunTimeControl: residualTolerance satisfied\n")

    criteria = knife_service.criteria_payload(case, lightweight=True, tail_bytes=256 * 1024)

    assert criteria["criteria_count"] >= 1
    assert criteria["passed"] >= 1


def test_real_toy_case_compare_reconstructed_parallel_to_serial(
    real_case: RealTutorialCase,
    tmp_path: Path,
) -> None:
    if not real_case.profile.supports_parallel:
        pytest.skip(f"{real_case.profile.name} does not support parallel scenario")
    if shutil.which("mpirun") is None and shutil.which("mpiexec") is None:
        pytest.skip("MPI launcher unavailable")

    source = real_case.case
    solver, _command = run_ops.solver_command(source)
    serial_case = tmp_path / "compare-serial"
    parallel_case = tmp_path / "compare-parallel"
    shutil.copytree(source, serial_case, ignore=shutil.ignore_patterns(".ofti"))
    shutil.copytree(source, parallel_case, ignore=shutil.ignore_patterns(".ofti"))
    _ensure_parallel_dict(parallel_case, 2)
    _require_working_parallel_launcher(run_ops.solver_command(parallel_case, parallel=2)[1])

    serial = run_ops.smoke_payload(
        serial_case,
        solver=solver,
        iterations=2,
        timeout=60,
        output_root=tmp_path / "serial-smoke",
        in_place=True,
        core_only=True,
    )
    parallel = run_ops.smoke_payload(
        parallel_case,
        solver=solver,
        iterations=2,
        timeout=90,
        parallel=2,
        output_root=tmp_path / "parallel-smoke",
        in_place=True,
        core_only=True,
        clean_processors=True,
    )
    assert serial["ok"] is True, serial
    assert parallel["ok"] is True, parallel
    assert serial["iterations_completed"] == 2
    assert parallel["iterations_completed"] == 2
    assert parallel["checkpoint_ok"] is True
    assert parallel["checkpoint"]["processor_count"] == 2
    assert parallel["latest_complete_processor_time"] is not None

    direct = knife_service.compare_fields_payload(
        serial_case,
        parallel_case,
        fields=["p", "U"],
    )
    assert direct["ok"] is True, direct
    assert direct["time_policy"] == "latest-common"
    assert direct["mesh"]["same"] is True
    assert all(row["count"] > 0 for row in direct["fields"])

    reconstructed_time = latest_time(parallel_case)
    result = run_ops.execute_case_command(
        parallel_case,
        "reconstructPar -latestTime",
        ["reconstructPar", "-latestTime"],
        background=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert (parallel_case / reconstructed_time).is_dir()

    compared = knife_service.compare_fields_payload(
        serial_case,
        parallel_case,
        reference_time=latest_time(serial_case),
        candidate_time=reconstructed_time,
        fields=["p", "U"],
        out_dir=tmp_path / "serial-vs-parallel-compare",
    )

    assert compared["ok"] is True, compared
    assert compared["field_count"] >= 1
    assert Path(str(compared["outputs"]["csv"])).is_file()
    for row in compared["fields"]:
        assert row["count"] > 0
        assert row["nonfinite_pairs"] == 0


def test_real_toy_case_prepare_parallel_extra_rank_profile(real_case: RealTutorialCase) -> None:
    if not real_case.profile.supports_parallel:
        pytest.skip(f"{real_case.profile.name} does not support parallel scenario")
    ranks = int(os.environ.get("OFTI_REAL_EXTRA_RANKS", "3"))
    if ranks < 2:
        pytest.skip("OFTI_REAL_EXTRA_RANKS must be >= 2")

    case = real_case.case
    real_case.ensure_parallel_dict(ranks)
    prepared = run_ops.prepare_parallel_case(case, parallel=ranks, clean_processors=True)

    assert prepared["decompose_returncode"] == 0
    for rank in range(ranks):
        assert (case / f"processor{rank}").is_dir()
    checkpoint = checkpoint_service.checkpoint_payload(case, expected_processors=ranks)
    assert checkpoint["ok"] is True
    assert checkpoint["latest_complete_time"] == "0"
    restart = checkpoint_service.restart_plan_payload(
        case,
        expected_processors=ranks,
        target_processors=ranks + 1,
    )
    assert restart["safe_to_apply"] is True
    assert restart["latest_common_time"] == "0"
    assert restart["mpi"]["consistent"] is True
    partial = case / "processor0" / "999"
    shutil.copytree(case / "processor0" / "0", partial)
    partial_plan = checkpoint_service.restart_plan_payload(
        case,
        expected_processors=ranks,
    )
    assert [row["time"] for row in partial_plan["partial_newer_times"]] == ["999"]
    preview = checkpoint_service.quarantine_partial_payload(
        case,
        expected_processors=ranks,
    )
    assert preview["applied"] is False
    assert preview["safe_to_apply"] is True
    quarantined = checkpoint_service.quarantine_partial_payload(
        case,
        expected_processors=ranks,
        apply=True,
    )
    assert quarantined["applied"] is True
    assert not partial.exists()
    assert Path(quarantined["moves"][0]["destination"]).is_dir()


def test_real_toy_case_parallel_prepare_run_stop_resize_plan(
    real_case: RealTutorialCase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if not real_case.profile.supports_parallel:
        pytest.skip(f"{real_case.profile.name} does not support parallel scenario")
    if shutil.which("mpirun") is None and shutil.which("mpiexec") is None:
        pytest.skip("MPI launcher unavailable")

    case = real_case.case
    _prepare_parallel_resize_source(real_case)

    code = cli_main(_resize_parallel_args(case))
    payload = json.loads(capsys.readouterr().out)
    steps = {str(row.get("step")): row for row in payload["steps"]}

    assert code == 0
    assert payload["ok"] is True
    assert payload["pid"] is not None
    assert steps["verify-processor-time"]["latest_processor_time"] == "999"
    assert steps["verify-processor-time"]["latest_complete_time"] == "1"
    assert steps["verify-processor-time"]["incomplete_latest_discarded"] is True
    assert steps["reconstruct"]["status"] == "done"
    assert steps["decompose"]["status"] == "done"
    assert steps["start"]["status"] == "done"
    assert (case / "processor0").is_dir()
    assert wait_until(lambda: running_jobs(case) >= 1, description="resized solver discovery") is None
    stopped = real_case.stop_all_solvers()
    assert stopped["selected"] >= 1
    wait_until(lambda: running_jobs(case) == 0, description="resized stopped solver")


def _prepare_parallel_resize_source(real_case: RealTutorialCase) -> None:
    case = real_case.case
    real_case.ensure_parallel_dict(2)
    _require_working_parallel_launcher(run_ops.solver_command(case, parallel=2)[1])
    prepared = run_ops.prepare_parallel_case(case, parallel=2, clean_processors=True)
    assert prepared["decompose_returncode"] == 0
    assert (case / "processor0").is_dir()
    dry_plan = parallel_resize_service.parallel_resize_payload(case, from_ranks=2, to_ranks=3, dry_run=True)
    assert dry_plan["ok"] is True
    assert dry_plan["restart_plan"]["safe_to_apply"] is True
    assert any(row["step"] == "decompose" for row in dry_plan["steps"])
    pid = real_case.start_solver(parallel=2)
    assert pid > 0
    wait_until(lambda: running_jobs(case) >= 1, description="parallel solver discovery")
    stopped = real_case.stop_all_solvers()
    assert stopped["selected"] >= 1
    wait_until(lambda: running_jobs(case) == 0, description="parallel stopped solver")
    for processor in ("processor0", "processor1"):
        shutil.copytree(case / processor / "0", case / processor / "1", dirs_exist_ok=True)
    (case / "processor0" / "999").mkdir(parents=True)
    (case / "processor0" / "999" / "U").write_text("partial incomplete time\n")


def _resize_parallel_args(case: Path) -> list[str]:
    return [
        "run",
        "resize-parallel",
        str(case),
        "--from",
        "2",
        "--to",
        os.environ.get("OFTI_REAL_RESIZE_TO", "3"),
        "--force-stop",
        "--json",
    ]


def _require_working_parallel_launcher(command: list[str]) -> None:
    if not command:
        pytest.skip("MPI launcher unavailable")
    probe = subprocess.run(  # noqa: S603
        [command[0], "-np", "1", "true"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip().splitlines()[:1]
        pytest.skip(f"MPI launcher unusable in this environment: {' '.join(detail)}")


def _ensure_parallel_dict(case: Path, ranks: int) -> None:
    path = case / "system" / "decomposeParDict"
    if path.is_file():
        assert (
            knife_service.set_entry_payload(
                case,
                "system/decomposeParDict",
                "numberOfSubdomains",
                str(ranks),
            )["ok"]
            is True
        )
        return
    path.write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class dictionary;",
                "    object decomposeParDict;",
                "}",
                f"numberOfSubdomains {ranks};",
                "method scotch;",
                "",
            ],
        ),
        encoding="utf-8",
    )


def _untracked_solver_count(case: Path) -> int:
    payload = knife_service.current_payload(case, live=True)
    return len(payload.get("untracked_processes", []))
