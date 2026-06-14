from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from ofti.tools import knife_service, parallel_resize_service, watch_service
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
    from ofti.core import run_manifest

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


def test_real_toy_case_parallel_prepare_run_stop_resize_plan(real_case: RealTutorialCase) -> None:
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
