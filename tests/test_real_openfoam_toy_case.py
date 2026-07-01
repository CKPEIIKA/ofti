from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from ofti.app.cli_tools import main as cli_main
from ofti.core import case_bundle, run_manifest
from ofti.foam.times import latest_time
from ofti.tools import (
    knife_service,
    parallel_resize_service,
    runtime_control_service,
    watch_service,
)
from ofti.tools.cli_tools import run as run_ops
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


def test_real_toy_case_bundle_unbundle_status(real_case: RealTutorialCase, tmp_path: Path) -> None:
    case = real_case.case
    archive = tmp_path / "real-case.ofti.tar.gz"
    manifest = case_bundle.create_bundle(case, archive, mesh="auto", time="0")
    restored = tmp_path / "restored"
    extracted = case_bundle.extract_bundle(archive, restored)

    assert extracted == manifest
    assert (restored / "system" / "controlDict").is_file()
    assert (restored / "constant" / "polyMesh").is_dir()
    assert not (restored / "postProcessing").exists()
    assert knife_service.preflight_payload(restored)["ok"] is True
    assert knife_service.status_payload(restored, lightweight=True)["case"] == str(restored)


def test_real_toy_case_unbundled_smoke_run_is_watchable(
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

def test_real_toy_case_parallel_prepare_run_stop_resize_plan(
    real_case: RealTutorialCase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if not real_case.profile.supports_parallel:
        pytest.skip(f"{real_case.profile.name} does not support parallel scenario")
    if shutil.which("mpirun") is None and shutil.which("mpiexec") is None:
        pytest.skip("MPI launcher unavailable")

    case = real_case.case
    real_case.ensure_parallel_dict(2)
    dry_plan = parallel_resize_service.parallel_resize_payload(case, from_ranks=2, to_ranks=3, dry_run=True)
    assert dry_plan["ok"] is True
    assert any(row["step"] == "decompose" for row in dry_plan["steps"])

    prepared = run_ops.prepare_parallel_case(case, parallel=2, clean_processors=True)
    assert prepared["decompose_returncode"] == 0
    assert (case / "processor0").is_dir()

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
    to_ranks = int(os.environ.get("OFTI_REAL_RESIZE_TO", "3"))

    code = cli_main(
        [
            "run",
            "resize-parallel",
            str(case),
            "--from",
            "2",
            "--to",
            str(to_ranks),
            "--force-stop",
            "--json",
        ],
    )
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



def _ensure_parallel_dict(case: Path, ranks: int) -> None:
    path = case / "system" / "decomposeParDict"
    if path.is_file():
        assert knife_service.set_entry_payload(
            case,
            "system/decomposeParDict",
            "numberOfSubdomains",
            str(ranks),
        )["ok"] is True
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
