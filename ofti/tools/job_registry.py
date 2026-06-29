from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JOBS_FORMAT = "ofti.jobs"
JOBS_FORMAT_VERSION = 1


def register_job(
    case_path: Path,
    name: str,
    pid: int,
    command: str,
    log_path: Path | None = None,
    *,
    kind: str = "solver",
    detached: bool | None = None,
    extra: dict[str, object] | None = None,
) -> str:
    jobs = load_jobs(case_path)
    job_id = f"{int(time.time())}-{pid}"
    started_at = time.time()
    row: dict[str, object] = {
        "id": job_id,
        "name": name,
        "kind": kind,
        "case_dir": str(case_path.resolve()),
        "pid": pid,
        "command": command,
        "log": str(log_path) if log_path else "",
        "status": "running",
        "started_at": started_at,
        "ended_at": None,
        "returncode": None,
        "launcher_pid": pid,
    }
    if detached is not None:
        row["detached"] = detached
    if extra:
        row.update(extra)
    jobs.append(row)
    save_jobs(case_path, jobs)
    _save_run_identity(case_path, row)
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
            _save_run_identity(case_path, job)
            break
    save_jobs(case_path, jobs)


def refresh_jobs(case_path: Path) -> list[dict[str, object]]:
    jobs = load_jobs(case_path)
    updated = _recover_running_identities(case_path, jobs)
    updated = _mark_finished_jobs(case_path, jobs) or updated
    if updated:
        save_jobs(case_path, jobs)
    return jobs


def _recover_running_identities(case_path: Path, jobs: list[dict[str, object]]) -> bool:
    updated = False
    known_ids = {str(job.get("id")) for job in jobs}
    for identity in load_run_identities(case_path):
        job_id = str(identity.get("id") or "")
        if not job_id or job_id in known_ids or not _identity_running(identity):
            continue
        jobs.append(_job_from_run_identity(identity))
        known_ids.add(job_id)
        updated = True
    return updated


def _mark_finished_jobs(case_path: Path, jobs: list[dict[str, object]]) -> bool:
    updated = False
    for job in jobs:
        if not _job_process_finished(job):
            continue
        job["status"] = "finished"
        job["ended_at"] = job.get("ended_at") or time.time()
        _save_run_identity(case_path, job)
        updated = True
    return updated


def _job_process_finished(job: dict[str, object]) -> bool:
    if job.get("status") not in {"running", "paused"}:
        return False
    pid = job.get("pid")
    return isinstance(pid, int) and not _pid_running(pid) and not _job_solver_running(job)


def load_jobs(case_path: Path) -> list[dict[str, object]]:
    path = _jobs_path(case_path)
    try:
        data = json.loads(path.read_text())
    except OSError:
        return []
    except json.JSONDecodeError:
        _quarantine_corrupt_jobs(path)
        return []
    if isinstance(data, dict):
        data = data.get("jobs")
    if not isinstance(data, list):
        return []
    return [job for job in data if isinstance(job, dict)]


def save_jobs(case_path: Path, jobs: list[dict[str, object]]) -> None:
    path = _jobs_path(case_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": JOBS_FORMAT,
        "format_version": JOBS_FORMAT_VERSION,
        "case_dir": str(case_path.resolve()),
        "updated_at": _utc_now(),
        "jobs": jobs,
    }
    _write_json_atomic(path, payload)


def load_run_identities(case_path: Path) -> list[dict[str, object]]:
    root = _runs_path(case_path)
    try:
        paths = sorted(root.glob("*.json"))
    except OSError:
        return []
    identities: list[dict[str, object]] = []
    for path in paths:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            identities.append(data)
    return identities


def _jobs_path(case_path: Path) -> Path:
    return case_path / ".ofti" / "jobs.json"


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _quarantine_corrupt_jobs(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"{path.name}.corrupt.{stamp}")
    with suppress(OSError):
        path.replace(target)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _runs_path(case_path: Path) -> Path:
    return case_path / ".ofti" / "runs"


def _current_run_path(case_path: Path) -> Path:
    return case_path / ".ofti" / "current_run.json"


def _save_run_identity(case_path: Path, job: dict[str, object]) -> None:
    job_id = str(job.get("id") or "")
    if not job_id:
        return
    identity = _run_identity_from_job(job)
    root = _runs_path(case_path)
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{job_id}.json").write_text(json.dumps(identity, indent=2, sort_keys=True))
    _current_run_path(case_path).write_text(json.dumps(identity, indent=2, sort_keys=True))


def _run_identity_from_job(job: dict[str, object]) -> dict[str, object]:
    solver_pids = _int_list(job.get("solver_pids"))
    pid = _int_or_none(job.get("pid"))
    launcher_pid = _int_or_none(job.get("launcher_pid")) or pid
    identity: dict[str, object] = {
        "id": str(job.get("id") or ""),
        "case_dir": str(job.get("case_dir") or ""),
        "kind": str(job.get("kind") or "solver"),
        "name": str(job.get("name") or ""),
        "launcher_pid": launcher_pid,
        "solver_pids": solver_pids,
        "command": str(job.get("command") or ""),
        "log": str(job.get("log") or ""),
        "status": str(job.get("status") or "running"),
        "started_at": _float_or_none(job.get("started_at")),
        "ended_at": _float_or_none(job.get("ended_at")),
        "returncode": _int_or_none(job.get("returncode")),
        "detached": bool(job.get("detached")) if "detached" in job else None,
    }
    for key in ("watcher_id", "env_keys", "adopted", "resumed_from"):
        if key in job:
            identity[key] = job[key]
    return identity


def _job_from_run_identity(identity: dict[str, object]) -> dict[str, object]:
    launcher_pid = _int_or_none(identity.get("launcher_pid"))
    solver_pids = _int_list(identity.get("solver_pids"))
    active_pid = _active_pid([launcher_pid, *solver_pids])
    job: dict[str, object] = {
        "id": str(identity.get("id") or ""),
        "name": str(identity.get("name") or "solver"),
        "kind": str(identity.get("kind") or "solver"),
        "case_dir": str(identity.get("case_dir") or ""),
        "pid": active_pid or launcher_pid or (solver_pids[0] if solver_pids else 0),
        "launcher_pid": launcher_pid,
        "solver_pids": solver_pids,
        "command": str(identity.get("command") or ""),
        "log": str(identity.get("log") or ""),
        "status": str(identity.get("status") or "running"),
        "started_at": _float_or_none(identity.get("started_at")) or time.time(),
        "ended_at": _float_or_none(identity.get("ended_at")),
        "returncode": _int_or_none(identity.get("returncode")),
        "recovered": True,
    }
    if "detached" in identity:
        job["detached"] = identity.get("detached")
    for key in ("watcher_id", "env_keys", "adopted", "resumed_from"):
        if key in identity:
            job[key] = identity[key]
    return job


def _identity_running(identity: dict[str, object]) -> bool:
    if str(identity.get("status") or "running") not in {"running", "paused"}:
        return False
    launcher_pid = _int_or_none(identity.get("launcher_pid"))
    return _active_pid([launcher_pid, *_int_list(identity.get("solver_pids"))]) is not None


def _job_solver_running(job: dict[str, object]) -> bool:
    return _active_pid(_int_list(job.get("solver_pids"))) is not None


def _active_pid(pids: Sequence[int | None]) -> int | None:
    for pid in pids:
        if isinstance(pid, int) and _pid_running(pid):
            return pid
    return None


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and item > 0]


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    else:
        if ") Z " in stat:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
