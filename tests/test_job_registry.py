from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from ofti.tools import job_registry
from ofti.tools.job_registry import (
    finish_job,
    load_jobs,
    load_run_identities,
    refresh_jobs,
    register_job,
    registry_warnings,
    repair_jobs_registry,
    save_jobs,
)


def test_job_registry_roundtrip(tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    case_path.mkdir()
    job_id = register_job(case_path, "solver", 99999, "solver", case_path / "log.solver")
    registry_payload = json.loads((case_path / ".ofti" / "jobs.json").read_text())
    assert registry_payload["format"] == "ofti.jobs"
    assert registry_payload["format_version"] == 1
    assert isinstance(registry_payload["jobs"], list)
    jobs = load_jobs(case_path)
    assert jobs
    assert jobs[0]["id"] == job_id
    identities = load_run_identities(case_path)
    assert identities
    assert identities[0]["id"] == job_id
    assert identities[0]["launcher_pid"] == 99999
    assert identities[0]["command"] == "solver"

    finish_job(case_path, job_id, "finished", 0)
    jobs = load_jobs(case_path)
    assert jobs[0]["status"] == "finished"
    assert jobs[0]["returncode"] == 0
    identities = load_run_identities(case_path)
    assert identities[0]["status"] == "finished"
    assert identities[0]["returncode"] == 0
    current = json.loads((case_path / ".ofti" / "current_run.json").read_text())
    assert current["status"] == "finished"


def test_job_registry_loads_legacy_raw_list_and_quarantines_corruption(tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    jobs_file = case_path / ".ofti" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text('[{"id": "legacy", "kind": "solver"}]', encoding="utf-8")

    assert load_jobs(case_path)[0]["id"] == "legacy"

    jobs_file.write_text("{bad json", encoding="utf-8")
    assert load_jobs(case_path) == []
    assert any(path.name.startswith("jobs.json.corrupt.") for path in jobs_file.parent.iterdir())
    assert registry_warnings(case_path)


def test_job_registry_rejects_unknown_wrapped_version(tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    jobs_file = case_path / ".ofti" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text(
        json.dumps({"format": "ofti.jobs", "format_version": 999, "jobs": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported jobs registry version"):
        load_jobs(case_path)


def test_refresh_jobs_rebuilds_registry_after_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_path = tmp_path / "case"
    case_path.mkdir()
    job_id = register_job(
        case_path,
        "solver",
        12345,
        "simpleFoam",
        case_path / "log.simpleFoam",
        extra={"solver_pids": [23456]},
    )
    jobs_file = case_path / ".ofti" / "jobs.json"
    jobs_file.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(job_registry, "_pid_running", lambda pid: pid == 23456)

    refreshed = refresh_jobs(case_path)

    assert refreshed[0]["id"] == job_id
    assert refreshed[0]["recovered"] is True
    rebuilt = json.loads(jobs_file.read_text(encoding="utf-8"))
    assert rebuilt["format"] == "ofti.jobs"
    assert rebuilt["jobs"][0]["id"] == job_id
    assert registry_warnings(case_path)


def test_repair_jobs_registry_recovers_non_live_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_path = tmp_path / "case"
    case_path.mkdir()
    job_id = register_job(case_path, "solver", 12345, "simpleFoam", case_path / "log.simpleFoam")
    save_jobs(case_path, [])
    monkeypatch.setattr(job_registry, "_pid_running", lambda _pid: False)

    payload = repair_jobs_registry(case_path)

    assert payload["rebuilt"] == 1
    repaired = load_jobs(case_path)
    assert repaired[0]["id"] == job_id
    assert repaired[0]["status"] == "finished"
    assert repaired[0]["recovered_stale"] is True


def test_refresh_jobs_marks_dead_pid(tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    case_path.mkdir()
    job_id = register_job(case_path, "solver", 99999, "solver", case_path / "log.solver")
    time.sleep(0.01)
    jobs = refresh_jobs(case_path)
    job = next(j for j in jobs if j["id"] == job_id)
    assert job["status"] in {"running", "finished"}


def test_refresh_jobs_marks_dead_paused_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case_path = tmp_path / "case"
    case_path.mkdir()
    job_id = register_job(case_path, "solver", 12345, "solver", case_path / "log.solver")
    jobs = load_jobs(case_path)
    jobs[0]["status"] = "paused"
    save_jobs(case_path, jobs)
    monkeypatch.setattr(job_registry, "_pid_running", lambda _pid: False)
    refreshed = refresh_jobs(case_path)
    job = next(j for j in refreshed if j["id"] == job_id)
    assert job["status"] == "finished"


def test_pid_running_treats_zombies_as_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: "123 (solver) Z 1 2 3")
    monkeypatch.setattr(os, "kill", lambda *_a, **_k: None)

    assert job_registry._pid_running(123) is False


def test_refresh_jobs_recovers_active_run_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_path = tmp_path / "case"
    case_path.mkdir()
    job_id = register_job(
        case_path,
        "solver",
        12345,
        "mpirun -np 2 simpleFoam -parallel",
        case_path / "log.simpleFoam",
        detached=True,
        extra={"solver_pids": [222, 333]},
    )
    save_jobs(case_path, [])
    monkeypatch.setattr(job_registry, "_pid_running", lambda pid: pid == 222)

    refreshed = refresh_jobs(case_path)

    job = next(j for j in refreshed if j["id"] == job_id)
    assert job["status"] == "running"
    assert job["pid"] == 222
    assert job["launcher_pid"] == 12345
    assert job["solver_pids"] == [222, 333]
    assert job["recovered"] is True
