from __future__ import annotations

import time
from pathlib import Path

import pytest

from ofti.tools import job_registry
from ofti.tools.job_registry import finish_job, load_jobs, refresh_jobs, register_job, save_jobs


def test_job_registry_roundtrip(tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    case_path.mkdir()
    job_id = register_job(case_path, "solver", 99999, "solver", case_path / "log.solver")
    jobs = load_jobs(case_path)
    assert jobs
    assert jobs[0]["id"] == job_id

    finish_job(case_path, job_id, "finished", 0)
    jobs = load_jobs(case_path)
    assert jobs[0]["status"] == "finished"
    assert jobs[0]["returncode"] == 0


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
