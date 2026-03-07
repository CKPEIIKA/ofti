from __future__ import annotations

import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict


class JobActionRow(TypedDict, total=False):
    id: str
    pid: int
    name: str
    error: str


class StopJobsPayload(TypedDict):
    signal: str
    selected: int
    stopped: list[JobActionRow]
    failed: list[JobActionRow]


class PauseJobsPayload(TypedDict):
    selected: int
    paused: list[JobActionRow]
    failed: list[JobActionRow]


class ResumeJobsPayload(TypedDict):
    selected: int
    resumed: list[JobActionRow]
    failed: list[JobActionRow]


def signal_by_name(signal_name: str) -> int:
    if signal_name == "TERM":
        return signal.SIGTERM
    if signal_name == "INT":
        return signal.SIGINT
    if signal_name == "KILL":
        return signal.SIGKILL
    if signal_name == "QUIT":
        return signal.SIGQUIT
    raise ValueError(f"unsupported signal: {signal_name}")


def select_jobs(
    jobs: list[dict[str, Any]],
    *,
    statuses: set[str],
    job_id: str | None,
    name: str | None,
    all_jobs: bool,
) -> list[dict[str, Any]]:
    candidates = [job for job in jobs if str(job.get("status")) in statuses]
    selected: list[dict[str, Any]] = []
    for job in candidates:
        if all_jobs:
            selected.append(job)
            continue
        if job_id and str(job.get("id")) == job_id:
            selected.append(job)
            continue
        if name and str(job.get("name")) == name:
            selected.append(job)
            continue
    if not all_jobs and not job_id and not name and candidates:
        selected = [candidates[0]]
    return selected


def set_job_status(
    case_path: Path,
    job_id: str,
    status: str,
    *,
    load_jobs_fn: Callable[[Path], list[dict[str, Any]]],
    save_jobs_fn: Callable[[Path, list[dict[str, Any]]], None],
) -> None:
    jobs = load_jobs_fn(case_path)
    for job in jobs:
        if str(job.get("id")) != job_id:
            continue
        job["status"] = status
        if status == "running":
            job["ended_at"] = None
            job["returncode"] = None
        break
    save_jobs_fn(case_path, jobs)


def stop_jobs(
    case_path: Path,
    jobs: list[dict[str, Any]],
    *,
    job_id: str | None,
    name: str | None,
    all_jobs: bool,
    signal_name: str,
    kill_fn: Callable[[int, int], None],
    finish_job_fn: Callable[[Path, str, str, int | None], None],
) -> StopJobsPayload:
    signal_code = signal_by_name(signal_name)
    selected = select_jobs(
        jobs,
        statuses={"running", "paused"},
        job_id=job_id,
        name=name,
        all_jobs=all_jobs,
    )

    stopped: list[JobActionRow] = []
    failed: list[JobActionRow] = []
    for job in selected:
        job_id_value = str(job.get("id", ""))
        job_name = str(job.get("name", ""))
        pid = job.get("pid")
        if not isinstance(pid, int):
            failed.append({"id": job_id_value, "error": "invalid pid"})
            continue
        try:
            kill_fn(pid, signal_code)
        except OSError as exc:
            finish_job_fn(case_path, job_id_value, "missing", None)
            failed.append({"id": job_id_value, "pid": pid, "error": str(exc)})
            continue
        finish_job_fn(case_path, job_id_value, "stopped", None)
        stopped.append({"id": job_id_value, "pid": pid, "name": job_name})

    return {
        "signal": signal_name,
        "selected": len(selected),
        "stopped": stopped,
        "failed": failed,
    }


def pause_jobs(
    case_path: Path,
    jobs: list[dict[str, Any]],
    *,
    job_id: str | None,
    name: str | None,
    all_jobs: bool,
    kill_fn: Callable[[int, int], None],
    finish_job_fn: Callable[[Path, str, str, int | None], None],
    set_status_fn: Callable[[Path, str, str], None],
) -> PauseJobsPayload:
    selected = select_jobs(
        jobs,
        statuses={"running"},
        job_id=job_id,
        name=name,
        all_jobs=all_jobs,
    )
    paused: list[JobActionRow] = []
    failed: list[JobActionRow] = []
    for job in selected:
        job_id_value = str(job.get("id", ""))
        job_name = str(job.get("name", ""))
        pid = job.get("pid")
        if not isinstance(pid, int):
            failed.append({"id": job_id_value, "error": "invalid pid"})
            continue
        try:
            kill_fn(pid, signal.SIGSTOP)
        except OSError as exc:
            finish_job_fn(case_path, job_id_value, "missing", None)
            failed.append({"id": job_id_value, "pid": pid, "error": str(exc)})
            continue
        set_status_fn(case_path, job_id_value, "paused")
        paused.append({"id": job_id_value, "pid": pid, "name": job_name})

    return {
        "selected": len(selected),
        "paused": paused,
        "failed": failed,
    }


def resume_jobs(
    case_path: Path,
    jobs: list[dict[str, Any]],
    *,
    job_id: str | None,
    name: str | None,
    all_jobs: bool,
    kill_fn: Callable[[int, int], None],
    finish_job_fn: Callable[[Path, str, str, int | None], None],
    set_status_fn: Callable[[Path, str, str], None],
) -> ResumeJobsPayload:
    selected = select_jobs(
        jobs,
        statuses={"paused"},
        job_id=job_id,
        name=name,
        all_jobs=all_jobs,
    )
    resumed: list[JobActionRow] = []
    failed: list[JobActionRow] = []
    for job in selected:
        job_id_value = str(job.get("id", ""))
        job_name = str(job.get("name", ""))
        pid = job.get("pid")
        if not isinstance(pid, int):
            failed.append({"id": job_id_value, "error": "invalid pid"})
            continue
        try:
            kill_fn(pid, signal.SIGCONT)
        except OSError as exc:
            finish_job_fn(case_path, job_id_value, "missing", None)
            failed.append({"id": job_id_value, "pid": pid, "error": str(exc)})
            continue
        set_status_fn(case_path, job_id_value, "running")
        resumed.append({"id": job_id_value, "pid": pid, "name": job_name})

    return {
        "selected": len(selected),
        "resumed": resumed,
        "failed": failed,
    }
