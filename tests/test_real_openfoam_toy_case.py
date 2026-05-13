from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

import pytest

from ofti.tools import (
    change_queue_service,
    cockpit_service,
    flight_deck_service,
    knife_service,
    launch_checklist_service,
    lint_service,
    mesh_radar_service,
    monitor_builder_service,
    numerics_service,
    parallel_resize_service,
    resource_watch_service,
    watch_service,
)
from ofti.tools.cli_tools import run as run_ops
from tests.real_openfoam_helpers import (
    RealCaseProfile,
    RealOpenFOAMCase,
    make_real_case,
    running_jobs,
    selected_real_profiles,
    tracked_solver_jobs,
    wait_payload,
    wait_until,
)

pytestmark = pytest.mark.real_openfoam


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "real_profile" not in metafunc.fixturenames:
        return
    profiles = selected_real_profiles()
    metafunc.parametrize("real_profile", profiles, ids=[profile.name for profile in profiles])


@pytest.fixture
def real_case(real_profile: RealCaseProfile, tmp_path: Path) -> Iterator[RealOpenFOAMCase]:
    case = make_real_case(real_profile, tmp_path)
    try:
        yield case
    finally:
        case.cleanup()


def test_real_case_prelaunch_decks(real_case: RealOpenFOAMCase) -> None:
    case = real_case.case
    assert knife_service.preflight_payload(case)["ok"] is True
    assert knife_service.initials_payload(case)["field_count"] >= 1

    checklist = launch_checklist_service.launch_checklist_payload(case)
    assert checklist["ready"] is True
    assert not checklist["blocking"]

    numerics = numerics_service.numerics_payload(case)
    assert {row["file"] for row in numerics["files"]} >= {
        "system/controlDict",
        "system/fvSchemes",
        "system/fvSolution",
    }
    assert all(row["status"] == "ok" for row in numerics["files"])

    mesh_radar = mesh_radar_service.mesh_radar_payload(case)
    assert mesh_radar["has_mesh"] is True
    assert mesh_radar["status"] in {"ok", "warn", "mesh"}

    resources = resource_watch_service.resource_watch_payload(case)
    assert resources["free_bytes"] is None or int(resources["free_bytes"]) > 0

    lint = lint_service.lint_payload(case)
    assert lint["errors"] == 0

    deck = cockpit_service.cockpit_payload(case)
    assert deck["case_dna"]["solver"]
    assert deck["mesh_radar"]["has_mesh"] is True

    monitor_plan = monitor_builder_service.monitor_builder_payload(case, include_diff=True)
    assert monitor_plan["changed"] is True
    assert "residuals" in "\n".join(monitor_plan["diff"])

    monitor_written = monitor_builder_service.monitor_builder_payload(case, write=True)
    assert monitor_written["written"] is True
    assert (case / "system" / "controlDict.functions").is_file()


def test_real_case_untracked_adoption(real_case: RealOpenFOAMCase) -> None:
    if not real_case.profile.supports_untracked_adoption:
        pytest.skip(f"{real_case.profile.name} does not support untracked-adoption scenario")
    case = real_case.case
    process = real_case.start_untracked_solver()
    assert process.pid > 0
    try:
        wait_payload(
            lambda: knife_service.current_payload(case, live=True),
            lambda payload: int(payload.get("jobs_running", 0)) >= 1
            and bool(payload.get("untracked_processes")),
            description="untracked solver discovery",
        )

        adopted = knife_service.adopt_payload(case, all_untracked=True)
        assert adopted["selected"] >= 1
        assert adopted["adopted"]
    finally:
        real_case.stop_all_solvers()
        with suppress(ProcessLookupError):
            process.terminate()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=4)
        if process.poll() is None:
            with suppress(ProcessLookupError):
                process.kill()
    wait_until(lambda: running_jobs(case) == 0, description="stopped adopted solver")


def test_real_case_tracked_lifecycle_and_runtime_mutation(real_case: RealOpenFOAMCase) -> None:
    case = real_case.case
    serial_pid = real_case.start_tracked_solver()
    assert serial_pid > 0
    wait_until(lambda: running_jobs(case) >= 1, description="tracked serial solver")

    current = knife_service.current_payload(case, live=True)
    assert int(current["jobs_running"]) >= 1
    assert watch_service.jobs_payload(case, include_all=False, kind="solver")["count"] >= 1

    status = knife_service.status_payload(case, lightweight=True, tail_bytes=256 * 1024)
    assert status["solver"]
    assert int(status["jobs_running"]) >= 1

    report = knife_service.report_payload(case, lightweight=True, tail_bytes=256 * 1024)
    assert report["case"] == str(case)
    assert report["solver"]
    report_markdown = knife_service.report_markdown(report)
    report_path = case / ".ofti-real-report.md"
    report_path.write_text(report_markdown, encoding="utf-8")
    assert "OFTI Report" in report_path.read_text(encoding="utf-8")

    flight = flight_deck_service.flight_deck_payload(case)
    assert int(flight["current"]["jobs_running"]) >= 1
    assert {row["key"] for row in flight["actions"]} >= {"s", "p", "u", "a"}

    root = real_case.root
    scope = knife_service.current_scope_payload(root, live=True, recursive=True)
    assert str(case) in scope.get("cases", [])
    assert int(scope.get("jobs_running", 0)) >= 1

    _assert_runtime_mutation_visible(case)
    _exercise_pause_resume_stop(case, real_case)


def test_real_case_parallel_restart(real_case: RealOpenFOAMCase) -> None:
    if not real_case.profile.supports_parallel:
        pytest.skip(f"{real_case.profile.name} does not support parallel-restart scenario")
    if shutil.which("mpirun") is None and shutil.which("mpiexec") is None:
        pytest.skip("MPI launcher unavailable")

    case = real_case.case
    real_case.set_control(writeInterval="1")
    real_case.ensure_parallel_dict(2)
    resize_plan = parallel_resize_service.parallel_resize_payload(
        case,
        from_ranks=2,
        to_ranks=3,
        dry_run=True,
    )
    assert resize_plan["ok"] is True
    assert any(row["step"] == "decompose" for row in resize_plan["steps"])
    prepared = run_ops.prepare_parallel_case(case, parallel=2, clean_processors=True)
    assert prepared["decompose_returncode"] == 0
    assert (case / "processor0").is_dir()

    lint = lint_service.lint_payload(case)
    assert not [
        row
        for row in lint["findings"]
        if row["rule"] == "decomposition" and row["severity"] == "WARN"
    ]

    parallel_pid = real_case.start_tracked_solver(parallel=2)
    assert parallel_pid > 0
    wait_until(lambda: running_jobs(case) >= 1, description="parallel solver")
    stopped = real_case.stop_all_solvers()
    assert stopped["selected"] >= 1
    wait_until(lambda: tracked_solver_jobs(case) == 0, description="stopped parallel solver")
    _assert_parallel_reconstructs_mesh(case, real_case)


def _assert_runtime_mutation_visible(case: Path) -> None:
    assert knife_service.set_entry_payload(case, "system/controlDict", "writeInterval", "0.5")[
        "ok"
    ] is True
    assert knife_service.set_entry_payload(case, "system/controlDict", "endTime", "200")[
        "ok"
    ] is True

    controls = numerics_service.numerics_payload(case)["controls"]
    values = {row["key"]: row["value"] for row in controls}
    assert str(values["endTime"]).rstrip(";") in {"200", "200.0"}
    assert str(values["writeInterval"]).rstrip(";") in {"0.5", "0.500000"}

    changes = change_queue_service.change_queue_payload(case)
    assert changes["source"] == "git"
    assert changes["count"] >= 1
    diff_text = "\n".join(changes["diff"])
    assert "endTime" in diff_text
    assert "writeInterval" in diff_text

    status = knife_service.status_payload(case, lightweight=True, tail_bytes=256 * 1024)
    runtime_control = status.get("run_time_control", {})
    assert str(runtime_control.get("end_time")).rstrip(";") in {"200", "200.0"}


def _assert_parallel_reconstructs_mesh(case: Path, real_case: RealOpenFOAMCase) -> None:
    real_case.run_tool("reconstructParMesh-constant", ["reconstructParMesh", "-constant"])
    assert (case / "constant" / "polyMesh").is_dir()


def _exercise_pause_resume_stop(case: Path, real_case: RealOpenFOAMCase) -> None:
    paused = watch_service.pause_payload(case, all_jobs=True, kind="solver")
    assert paused["selected"] >= 1
    wait_until(
        lambda: watch_service.jobs_payload(case, include_all=False, kind="solver")["count"] >= 1,
        description="paused solver registry row",
    )

    resumed = watch_service.resume_payload(case, all_jobs=True, kind="solver")
    assert resumed["selected"] >= 1
    wait_until(lambda: running_jobs(case) >= 1, description="resumed solver")

    stopped = real_case.stop_all_solvers()
    assert stopped["selected"] >= 1
    wait_until(lambda: tracked_solver_jobs(case) == 0, description="stopped solver")
