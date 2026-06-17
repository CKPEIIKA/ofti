"""External-watcher payloads (extracted from watch_service).

Adopting/observing externally launched watcher processes. Shared job helpers
(_job_with_schema, _infer_job_kind) stay in watch_service and are reached via
the lazy ``_ws()`` accessor to avoid an import cycle.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from ofti.tools import case_source_service, job_control_service

ExternalWatchMode = Literal["run", "start", "status", "attach", "stop"]
_WATCHER_KIND = "watcher"


def _ws() -> Any:
    from ofti.tools import watch_service

    return watch_service


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

    process = subprocess.Popen(command, cwd=case_path)
    payload["pid"] = process.pid
    returncode = process.wait()
    payload["returncode"] = returncode
    payload["ok"] = returncode == 0
    return payload


def external_watch_mode(
    *,
    start: bool = False,
    status: bool = False,
    attach: bool = False,
    stop: bool = False,
) -> ExternalWatchMode | None:
    selected = sum(1 for flag in (start, status, attach, stop) if flag)
    if selected > 1:
        return None
    if start:
        return "start"
    if status:
        return "status"
    if attach:
        return "attach"
    if stop:
        return "stop"
    return "run"


def normalize_external_command(command: list[str]) -> list[str]:
    if command and command[0] == "--":
        return command[1:]
    return command


def external_watch_mode_payload(
    case_dir: Path,
    *,
    mode: ExternalWatchMode,
    command: list[str],
    dry_run: bool,
    name: str = "watch.external",
    detached: bool = True,
    log_file: str | None = None,
    job_id: str | None = None,
    include_all: bool = False,
    all_jobs: bool = False,
    lines: int = 40,
    signal_name: str = "TERM",
) -> dict[str, Any]:
    if mode == "start":
        return _ws().external_watch_start_payload(
            case_dir,
            command=command,
            dry_run=dry_run,
            name=name,
            detached=detached,
            log_file=log_file,
        )
    if mode == "status":
        return _ws().external_watch_status_payload(
            case_dir,
            job_id=job_id,
            name=name,
            include_all=include_all,
        )
    if mode == "attach":
        return _ws().external_watch_attach_payload(
            case_dir,
            lines=lines,
            job_id=job_id,
            name=name,
        )
    if mode == "stop":
        return _ws().external_watch_stop_payload(
            case_dir,
            job_id=job_id,
            name=name,
            all_jobs=all_jobs,
            signal_name=signal_name,
        )
    return external_watch_payload(
        case_dir,
        command=command,
        dry_run=dry_run,
    )


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
    process = subprocess.Popen(
        command,
        cwd=case_path,
        stdout=handle,
        stderr=handle,
        text=True,
        start_new_session=detached,
    )
    handle.close()
    payload["pid"] = process.pid
    job_id = _ws().register_job(
        case_path,
        name,
        int(process.pid),
        " ".join(command),
        log_path,
        kind=_WATCHER_KIND,
        detached=detached,
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
    jobs = [_ws()._job_with_schema(case_path, job) for job in _ws().refresh_jobs(case_path)]
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
    log_path = _ws()._log_path_from_job(case_path, str(selected.get("id")))
    payload = _ws()._tail_payload_from_log(log_path, lines=lines)
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
    jobs = _ws().refresh_jobs(case_path)
    rows = _external_jobs(jobs, name=name)
    control = job_control_service.stop_jobs(
        case_path,
        rows,
        job_id=job_id,
        name=name or None,
        all_jobs=all_jobs,
        signal_name=signal_name,
        kill_fn=os.kill,
        finish_job_fn=_ws().finish_job,
        killpg_fn=os.killpg,
        getpgid_fn=os.getpgid,
    )
    return {
        "case": str(case_path),
        "name": name,
        "selected": control["selected"],
        "stopped": control["stopped"],
        "failed": control["failed"],
        "signal": control["signal"],
    }


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
        if _ws()._infer_job_kind(job) != _WATCHER_KIND:
            continue
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
    jobs = _ws().refresh_jobs(case_path)
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
