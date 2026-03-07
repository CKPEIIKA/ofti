from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from ofti.tools.job_registry import finish_job, load_jobs, refresh_jobs, save_jobs

from .common import read_text, require_case_dir, resolve_log_source


def jobs_payload(case_dir: Path, *, include_all: bool) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    jobs = refresh_jobs(case_path)
    if not include_all:
        jobs = [job for job in jobs if job.get("status") in {"running", "paused"}]
    return {"case": str(case_path), "count": len(jobs), "jobs": jobs}


def log_tail_payload(source: Path, *, lines: int) -> dict[str, Any]:
    log_path = resolve_log_source(source)
    tail_lines: list[str] = []
    if lines > 0:
        tail_lines = read_text(log_path).splitlines()[-lines:]
    return {"log": str(log_path), "lines": tail_lines}


def log_tail_payload_for_job(case_dir: Path, *, job_id: str, lines: int) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    log_path = _log_path_from_job(case_path, job_id)
    tail_lines: list[str] = []
    if lines > 0:
        tail_lines = read_text(log_path).splitlines()[-lines:]
    return {"log": str(log_path), "lines": tail_lines}


def stop_payload(
    case_dir: Path,
    *,
    job_id: str | None = None,
    name: str | None = None,
    all_jobs: bool = False,
    signal_name: str = "TERM",
) -> dict[str, Any]:
    signal_name = signal_name.strip().upper()
    signal_code = _signal_by_name(signal_name)
    case_path = require_case_dir(case_dir)
    jobs = refresh_jobs(case_path)
    selected = _select_jobs(
        jobs,
        statuses={"running", "paused"},
        job_id=job_id,
        name=name,
        all_jobs=all_jobs,
    )

    stopped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for job in selected:
        pid = job.get("pid")
        if not isinstance(pid, int):
            failed.append({"id": job.get("id"), "error": "invalid pid"})
            continue
        try:
            os.kill(pid, signal_code)
        except OSError as exc:
            finish_job(case_path, str(job.get("id", "")), "missing", None)
            failed.append({"id": job.get("id"), "pid": pid, "error": str(exc)})
            continue
        finish_job(case_path, str(job.get("id", "")), "stopped", None)
        stopped.append({"id": job.get("id"), "pid": pid, "name": job.get("name")})

    return {
        "case": str(case_path),
        "signal": signal_name,
        "selected": len(selected),
        "stopped": stopped,
        "failed": failed,
    }


def pause_payload(
    case_dir: Path,
    *,
    job_id: str | None = None,
    name: str | None = None,
    all_jobs: bool = False,
) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    jobs = refresh_jobs(case_path)
    selected = _select_jobs(
        jobs,
        statuses={"running"},
        job_id=job_id,
        name=name,
        all_jobs=all_jobs,
    )
    paused: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for job in selected:
        pid = job.get("pid")
        if not isinstance(pid, int):
            failed.append({"id": job.get("id"), "error": "invalid pid"})
            continue
        try:
            os.kill(pid, signal.SIGSTOP)
        except OSError as exc:
            finish_job(case_path, str(job.get("id", "")), "missing", None)
            failed.append({"id": job.get("id"), "pid": pid, "error": str(exc)})
            continue
        _set_job_status(case_path, str(job.get("id", "")), "paused")
        paused.append({"id": job.get("id"), "pid": pid, "name": job.get("name")})
    return {
        "case": str(case_path),
        "selected": len(selected),
        "paused": paused,
        "failed": failed,
    }


def resume_payload(
    case_dir: Path,
    *,
    job_id: str | None = None,
    name: str | None = None,
    all_jobs: bool = False,
) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    jobs = refresh_jobs(case_path)
    selected = _select_jobs(
        jobs,
        statuses={"paused"},
        job_id=job_id,
        name=name,
        all_jobs=all_jobs,
    )
    resumed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for job in selected:
        pid = job.get("pid")
        if not isinstance(pid, int):
            failed.append({"id": job.get("id"), "error": "invalid pid"})
            continue
        try:
            os.kill(pid, signal.SIGCONT)
        except OSError as exc:
            finish_job(case_path, str(job.get("id", "")), "missing", None)
            failed.append({"id": job.get("id"), "pid": pid, "error": str(exc)})
            continue
        _set_job_status(case_path, str(job.get("id", "")), "running")
        resumed.append({"id": job.get("id"), "pid": pid, "name": job.get("name")})
    return {
        "case": str(case_path),
        "selected": len(selected),
        "resumed": resumed,
        "failed": failed,
    }


def external_watch_payload(
    case_dir: Path,
    *,
    command: list[str],
    dry_run: bool,
) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    payload: dict[str, Any] = {
        "case": str(case_path),
        "command": command,
        "dry_run": dry_run,
    }
    if dry_run:
        payload["ok"] = True
        return payload
    if not command:
        raise ValueError("external watcher command is required")

    process = subprocess.Popen(command, cwd=case_path)  # noqa: S603
    payload["pid"] = process.pid
    returncode = process.wait()
    payload["returncode"] = returncode
    payload["ok"] = returncode == 0
    return payload


def _log_path_from_job(case_path: Path, job_id: str) -> Path:
    jobs = load_jobs(case_path)
    for job in jobs:
        if str(job.get("id")) != str(job_id):
            continue
        log_raw = str(job.get("log") or "").strip()
        if not log_raw:
            raise ValueError(f"job {job_id} has no log path")
        log_path = Path(log_raw).expanduser()
        if not log_path.is_absolute():
            log_path = case_path / log_path
        log_path = log_path.resolve()
        if not log_path.is_file():
            raise ValueError(f"log for job {job_id} not found: {log_path}")
        return log_path
    raise ValueError(f"job not found: {job_id}")


def _signal_by_name(signal_name: str) -> int:
    if signal_name == "TERM":
        return signal.SIGTERM
    if signal_name == "INT":
        return signal.SIGINT
    if signal_name == "KILL":
        return signal.SIGKILL
    if signal_name == "QUIT":
        return signal.SIGQUIT
    raise ValueError(f"unsupported signal: {signal_name}")


def _select_jobs(
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


def _set_job_status(case_path: Path, job_id: str, status: str) -> None:
    jobs = load_jobs(case_path)
    for job in jobs:
        if str(job.get("id")) != job_id:
            continue
        job["status"] = status
        if status == "running":
            job["ended_at"] = None
            job["returncode"] = None
        break
    save_jobs(case_path, jobs)
