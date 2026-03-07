from __future__ import annotations

import os
import signal as _signal
import subprocess
from pathlib import Path
from typing import Any

from ofti.foamlib.logs import read_log_tail_lines
from ofti.tools import case_source_service, job_control_service
from ofti.tools.job_registry import finish_job, load_jobs, refresh_jobs, register_job, save_jobs

signal = _signal


def jobs_payload(case_dir: Path, *, include_all: bool) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    jobs = refresh_jobs(case_path)
    if not include_all:
        jobs = [job for job in jobs if job.get("status") in {"running", "paused"}]
    return {"case": str(case_path), "count": len(jobs), "jobs": jobs}


def _tail_payload_from_log(log_path: Path, *, lines: int) -> dict[str, Any]:
    tail_lines: list[str] = []
    if lines > 0:
        try:
            tail_lines = read_log_tail_lines(log_path, max_lines=lines)
        except OSError as exc:
            raise ValueError(f"failed to read {log_path}: {exc}") from exc
    return {"log": str(log_path), "lines": tail_lines}


def log_tail_payload(source: Path, *, lines: int) -> dict[str, Any]:
    log_path = case_source_service.resolve_log_source(source)
    return _tail_payload_from_log(log_path, lines=lines)


def log_tail_payload_for_job(case_dir: Path, *, job_id: str, lines: int) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    log_path = _log_path_from_job(case_path, job_id)
    return _tail_payload_from_log(log_path, lines=lines)


def stop_payload(
    case_dir: Path,
    *,
    job_id: str | None = None,
    name: str | None = None,
    all_jobs: bool = False,
    signal_name: str = "TERM",
) -> dict[str, Any]:
    signal_name = signal_name.strip().upper()
    return _job_action_payload(
        case_dir,
        action="stopped",
        run_control_fn=lambda case_path, jobs: job_control_service.stop_jobs(
            case_path,
            jobs,
            job_id=job_id,
            name=name,
            all_jobs=all_jobs,
            signal_name=signal_name,
            kill_fn=os.kill,
            finish_job_fn=finish_job,
        ),
    )


def pause_payload(
    case_dir: Path,
    *,
    job_id: str | None = None,
    name: str | None = None,
    all_jobs: bool = False,
) -> dict[str, Any]:
    return _job_action_payload(
        case_dir,
        action="paused",
        run_control_fn=lambda case_path, jobs: job_control_service.pause_jobs(
            case_path,
            jobs,
            job_id=job_id,
            name=name,
            all_jobs=all_jobs,
            kill_fn=os.kill,
            finish_job_fn=finish_job,
            set_status_fn=_set_job_status,
        ),
    )


def resume_payload(
    case_dir: Path,
    *,
    job_id: str | None = None,
    name: str | None = None,
    all_jobs: bool = False,
) -> dict[str, Any]:
    return _job_action_payload(
        case_dir,
        action="resumed",
        run_control_fn=lambda case_path, jobs: job_control_service.resume_jobs(
            case_path,
            jobs,
            job_id=job_id,
            name=name,
            all_jobs=all_jobs,
            kill_fn=os.kill,
            finish_job_fn=finish_job,
            set_status_fn=_set_job_status,
        ),
    )


def external_watch_payload(
    case_dir: Path,
    *,
    command: list[str],
    dry_run: bool,
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
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


def external_watch_start_payload(
    case_dir: Path,
    *,
    command: list[str],
    dry_run: bool,
    name: str = "watch.external",
    detached: bool = True,
    log_file: str | None = None,
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    if not command and not dry_run:
        raise ValueError("external watcher command is required")
    log_path = _external_log_path(case_path, name=name, raw=log_file)
    payload: dict[str, Any] = {
        "case": str(case_path),
        "command": command,
        "name": name,
        "detached": detached,
        "log_path": str(log_path),
        "dry_run": dry_run,
    }
    if dry_run:
        payload["ok"] = True
        return payload

    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8", errors="ignore")
    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=case_path,
        stdout=handle,
        stderr=handle,
        text=True,
        start_new_session=detached,
    )
    handle.close()
    payload["pid"] = process.pid
    job_id = register_job(
        case_path,
        name,
        int(process.pid),
        " ".join(command),
        log_path,
    )
    payload["job_id"] = job_id
    payload["ok"] = True
    return payload


def external_watch_status_payload(
    case_dir: Path,
    *,
    job_id: str | None = None,
    name: str = "watch.external",
    include_all: bool = False,
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    jobs = refresh_jobs(case_path)
    rows = _external_jobs(jobs, name=name)
    if job_id is not None:
        rows = [job for job in rows if str(job.get("id")) == str(job_id)]
    if not include_all:
        rows = [job for job in rows if str(job.get("status")) in {"running", "paused"}]
    return {
        "case": str(case_path),
        "name": name,
        "count": len(rows),
        "jobs": rows,
    }


def external_watch_attach_payload(
    case_dir: Path,
    *,
    lines: int,
    job_id: str | None = None,
    name: str = "watch.external",
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    selected = _select_external_job(case_path, job_id=job_id, name=name)
    log_path = _log_path_from_job(case_path, str(selected.get("id")))
    payload = _tail_payload_from_log(log_path, lines=lines)
    payload["job_id"] = selected.get("id")
    payload["name"] = selected.get("name")
    payload["case"] = str(case_path)
    return payload


def external_watch_stop_payload(
    case_dir: Path,
    *,
    job_id: str | None = None,
    name: str = "watch.external",
    all_jobs: bool = False,
    signal_name: str = "TERM",
) -> dict[str, Any]:
    signal_name = signal_name.strip().upper()
    case_path = case_source_service.require_case_dir(case_dir)
    jobs = refresh_jobs(case_path)
    rows = _external_jobs(jobs, name=name)
    control = job_control_service.stop_jobs(
        case_path,
        rows,
        job_id=job_id,
        name=name if name else None,
        all_jobs=all_jobs,
        signal_name=signal_name,
        kill_fn=os.kill,
        finish_job_fn=finish_job,
    )
    return {
        "case": str(case_path),
        "name": name,
        "selected": control["selected"],
        "stopped": control["stopped"],
        "failed": control["failed"],
        "signal": control["signal"],
    }


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


def _external_log_path(case_path: Path, *, name: str, raw: str | None) -> Path:
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = case_path / candidate
        return candidate.resolve()
    safe_name = "".join(
        ch for ch in name if ch.isalnum() or ch in {"-", "_", "."}
    ) or "watch.external"
    return (case_path / f"log.{safe_name}").resolve()


def _external_jobs(jobs: list[dict[str, Any]], *, name: str) -> list[dict[str, Any]]:
    prefix = name.strip()
    if not prefix:
        prefix = "watch.external"
    rows: list[dict[str, Any]] = []
    for job in jobs:
        job_name = str(job.get("name") or "")
        if job_name == prefix or job_name.startswith(f"{prefix}."):
            rows.append(job)
    return rows


def _select_external_job(
    case_path: Path,
    *,
    job_id: str | None,
    name: str,
) -> dict[str, Any]:
    jobs = refresh_jobs(case_path)
    rows = _external_jobs(jobs, name=name)
    if job_id is not None:
        for job in rows:
            if str(job.get("id")) == str(job_id):
                return job
        raise ValueError(f"external watcher job not found: {job_id}")
    running = [job for job in rows if str(job.get("status")) in {"running", "paused"}]
    pool = running or rows
    if not pool:
        raise ValueError(f"no tracked external watcher jobs for {name}")
    pool.sort(key=lambda item: float(item.get("started_at") or 0.0), reverse=True)
    return pool[0]


def _signal_by_name(signal_name: str) -> int:
    return job_control_service.signal_by_name(signal_name)


def _select_jobs(
    jobs: list[dict[str, Any]],
    *,
    statuses: set[str],
    job_id: str | None,
    name: str | None,
    all_jobs: bool,
) -> list[dict[str, Any]]:
    return job_control_service.select_jobs(
        jobs,
        statuses=statuses,
        job_id=job_id,
        name=name,
        all_jobs=all_jobs,
    )


def _set_job_status(case_path: Path, job_id: str, status: str) -> None:
    job_control_service.set_job_status(
        case_path,
        job_id,
        status,
        load_jobs_fn=load_jobs,
        save_jobs_fn=save_jobs,
    )


def _job_action_payload(
    case_dir: Path,
    *,
    action: str,
    run_control_fn,
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    jobs = refresh_jobs(case_path)
    control = run_control_fn(case_path, jobs)
    payload = {
        "case": str(case_path),
        "selected": control["selected"],
        "failed": control["failed"],
        action: control[action],
    }
    if "signal" in control:
        payload["signal"] = control["signal"]
    return payload
