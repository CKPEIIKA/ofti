from __future__ import annotations

import json
import os
import time
from pathlib import Path


def register_job(
    case_path: Path,
    name: str,
    pid: int,
    command: str,
    log_path: Path | None = None,
) -> str:
    jobs = load_jobs(case_path)
    job_id = f"{int(time.time())}-{pid}"
    jobs.append(
        {
            "id": job_id,
            "name": name,
            "pid": pid,
            "command": command,
            "log": str(log_path) if log_path else "",
            "status": "running",
            "started_at": time.time(),
            "ended_at": None,
            "returncode": None,
        },
    )
    save_jobs(case_path, jobs)
    return job_id


def finish_job(
    case_path: Path,
    job_id: str | None,
    status: str,
    returncode: int | None = None,
) -> None:
    if not job_id:
        return
    jobs = load_jobs(case_path)
    for job in jobs:
        if job.get("id") == job_id:
            job["status"] = status
            job["ended_at"] = time.time()
            job["returncode"] = returncode
            break
    save_jobs(case_path, jobs)


def refresh_jobs(case_path: Path) -> list[dict[str, object]]:
    jobs = load_jobs(case_path)
    updated = False
    for job in jobs:
        if job.get("status") == "running":
            pid = job.get("pid")
            if isinstance(pid, int) and not _pid_running(pid):
                job["status"] = "finished"
                job["ended_at"] = job.get("ended_at") or time.time()
                updated = True
    if updated:
        save_jobs(case_path, jobs)
    return jobs


def load_jobs(case_path: Path) -> list[dict[str, object]]:
    path = _jobs_path(case_path)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [job for job in data if isinstance(job, dict)]


def save_jobs(case_path: Path, jobs: list[dict[str, object]]) -> None:
    path = _jobs_path(case_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jobs, indent=2, sort_keys=True))


def _jobs_path(case_path: Path) -> Path:
    return case_path / ".ofti" / "jobs.json"


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
