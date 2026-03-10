from __future__ import annotations

import json
import os
import shlex
import signal as _signal
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from ofti.foam.subprocess_utils import run_trusted
from ofti.foamlib.logs import read_log_tail_lines
from ofti.tools import (
    case_source_service,
    job_control_service,
    process_scan_service,
    runner_service,
)
from ofti.tools.helpers import with_bashrc
from ofti.tools.job_registry import finish_job, load_jobs, refresh_jobs, register_job, save_jobs

signal = _signal
ExternalWatchMode = Literal["run", "start", "status", "attach", "stop"]
WatchOutputProfile = Literal["brief", "detailed"]
_WATCH_SETTINGS_DEFAULT_INTERVAL = 0.25
_WATCH_SETTINGS_DEFAULT_OUTPUT: WatchOutputProfile = "detailed"
_WATCHER_KIND = "watcher"
_SOLVER_KIND = "solver"
_WATCHER_ENV_FORWARD_KEYS = (
    "MIND_URL",
    "CONTROL_API_TOKEN",
    "RELAY_BASE_URL",
    "RELAY_SECRET",
    "RELAY_CA_CERT",
)


def jobs_payload(
    case_dir: Path,
    *,
    include_all: bool,
    kind: str | None = None,
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    jobs = refresh_jobs(case_path)
    selected_kind = _normalize_kind_filter(kind)
    if not include_all:
        jobs = [job for job in jobs if job.get("status") in {"running", "paused"}]
    shaped = [_job_with_schema(case_path, job) for job in jobs]
    if selected_kind is not None:
        shaped = [job for job in shaped if str(job.get("kind")) == selected_kind]
    return {
        "case": str(case_path),
        "count": len(shaped),
        "kind": selected_kind or "any",
        "jobs": shaped,
    }


def start_payload(
    case_dir: Path,
    *,
    name: str,
    command: list[str],
    detached: bool = True,
    log_file: str | None = None,
    dry_run: bool = False,
    kind: str = _SOLVER_KIND,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    normalized_kind = _normalize_kind_filter(kind) or _SOLVER_KIND
    if normalized_kind not in {_SOLVER_KIND, _WATCHER_KIND}:
        raise ValueError(f"unsupported job kind: {kind}")
    resolved_command = normalize_external_command(list(command))
    if not resolved_command and not dry_run:
        raise ValueError("command is required")
    log_path = _external_log_path(case_path, name=name, raw=log_file)
    payload: dict[str, Any] = {
        "case": str(case_path),
        "name": name,
        "kind": normalized_kind,
        "command": resolved_command,
        "detached": detached,
        "log_path": str(log_path),
        "dry_run": dry_run,
    }
    if env:
        payload["env_keys"] = sorted(env)
    if dry_run:
        payload["ok"] = True
        return payload

    holder: dict[str, str] = {}

    def _register(
        register_case: Path,
        register_name: str,
        pid: int,
        command_text: str,
        log: Path | None,
    ) -> str:
        job_id = register_job(
            register_case,
            register_name,
            pid,
            command_text,
            log,
            kind=normalized_kind,
            detached=detached,
        )
        holder["job_id"] = job_id
        return job_id

    result = runner_service.execute_case_command(
        case_path,
        name,
        resolved_command,
        background=True,
        detached=detached,
        log_path=log_path,
        extra_env=env,
        with_bashrc_fn=with_bashrc,
        run_trusted_fn=run_trusted,
        popen_fn=subprocess.Popen,
        register_job_fn=_register,
    )
    if result.pid is None:
        raise ValueError("missing background pid")
    payload["pid"] = int(result.pid)
    payload["job_id"] = holder.get("job_id")
    payload["ok"] = True
    return payload


def interval_payload(case_dir: Path, *, seconds: float | None = None) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    settings = _load_watch_settings(case_path)
    changed = False
    requested: float | None = None
    if seconds is not None:
        if seconds <= 0:
            raise ValueError("interval must be > 0")
        requested = float(seconds)
        settings["interval"] = requested
        _save_watch_settings(case_path, settings)
        changed = True
    effective = _watch_interval(settings)
    return {
        "case": str(case_path),
        "changed": changed,
        "requested": requested,
        "effective": effective,
        "settings_path": str(_watch_settings_path(case_path)),
    }


def output_profile_payload(
    case_dir: Path,
    *,
    profile: WatchOutputProfile | None = None,
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    settings = _load_watch_settings(case_path)
    changed = False
    requested: str | None = None
    if profile is not None:
        requested = str(profile)
        settings["output"] = requested
        _save_watch_settings(case_path, settings)
        changed = True
    effective = _watch_output(settings)
    return {
        "case": str(case_path),
        "changed": changed,
        "requested": requested,
        "effective": effective,
        "settings_path": str(_watch_settings_path(case_path)),
    }


def effective_interval(case_dir: Path) -> float:
    case_path = case_source_service.require_case_dir(case_dir)
    settings = _load_watch_settings(case_path)
    return _watch_interval(settings)


def effective_output_profile(case_dir: Path) -> WatchOutputProfile:
    case_path = case_source_service.require_case_dir(case_dir)
    settings = _load_watch_settings(case_path)
    return _watch_output(settings)


def watcher_preset_payload(case_dir: Path) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    command, env, preset_path = _resolve_watcher_command(case_path, None)
    return {
        "case": str(case_path),
        "preset_path": str(preset_path) if preset_path is not None else None,
        "command": command,
        "env": env,
        "found": bool(command),
    }


def watcher_start_payload(
    case_dir: Path,
    *,
    command: list[str] | None,
    detached: bool = True,
    log_file: str | None = None,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
    name: str = "watcher",
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    resolved_command, preset_env, preset_path = _resolve_watcher_command(case_path, command)
    if not resolved_command and not dry_run:
        if preset_path is None:
            raise ValueError("watcher command is required or define preset in ofti.watcher")
        raise ValueError(f"watcher command not found in preset: {preset_path}")
    watcher_id = (
        str((env or {}).get("WATCHER_ID") or "")
        or f"watcher-{int(time.time())}"
    )
    merged_env = _watcher_env(
        case_path,
        watcher_id=watcher_id,
        preset_env=preset_env,
        extra_env=env,
    )
    log_path = _external_log_path(case_path, name=name, raw=log_file)
    payload: dict[str, Any] = {
        "case": str(case_path),
        "kind": _WATCHER_KIND,
        "name": name,
        "command": resolved_command,
        "detached": detached,
        "log_path": str(log_path),
        "env_keys": sorted(merged_env),
        "watcher_id": watcher_id,
        "preset_path": str(preset_path) if preset_path is not None else None,
        "dry_run": dry_run,
    }
    if dry_run:
        payload["ok"] = True
        return payload

    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8", errors="ignore")
    process = subprocess.Popen(  # noqa: S603
        resolved_command,
        cwd=case_path,
        stdout=handle,
        stderr=handle,
        text=True,
        env=merged_env,
        start_new_session=detached,
    )
    handle.close()
    payload["pid"] = int(process.pid)
    job_id = register_job(
        case_path,
        name,
        int(process.pid),
        " ".join(resolved_command),
        log_path,
        kind=_WATCHER_KIND,
        detached=detached,
        extra={
            "watcher_id": watcher_id,
            "env_keys": sorted(merged_env),
        },
    )
    payload["job_id"] = job_id
    payload["ok"] = True
    return payload


def watcher_run_payload(
    case_dir: Path,
    *,
    command: list[str] | None,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
    name: str = "watcher",
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    resolved_command, preset_env, preset_path = _resolve_watcher_command(case_path, command)
    if not resolved_command and not dry_run:
        if preset_path is None:
            raise ValueError("watcher command is required or define preset in ofti.watcher")
        raise ValueError(f"watcher command not found in preset: {preset_path}")
    watcher_id = (
        str((env or {}).get("WATCHER_ID") or "")
        or f"watcher-{int(time.time())}"
    )
    merged_env = _watcher_env(
        case_path,
        watcher_id=watcher_id,
        preset_env=preset_env,
        extra_env=env,
    )
    payload: dict[str, Any] = {
        "case": str(case_path),
        "kind": _WATCHER_KIND,
        "name": name,
        "command": resolved_command,
        "detached": False,
        "env_keys": sorted(merged_env),
        "watcher_id": watcher_id,
        "preset_path": str(preset_path) if preset_path is not None else None,
        "dry_run": dry_run,
    }
    if dry_run:
        payload["ok"] = True
        return payload
    process = subprocess.Popen(  # noqa: S603
        resolved_command,
        cwd=case_path,
        text=True,
        env=merged_env,
    )
    payload["pid"] = int(process.pid)
    job_id = register_job(
        case_path,
        name,
        int(process.pid),
        " ".join(resolved_command),
        None,
        kind=_WATCHER_KIND,
        detached=False,
        extra={"watcher_id": watcher_id},
    )
    payload["job_id"] = job_id
    returncode = process.wait()
    status = "finished" if returncode == 0 else "failed"
    finish_job(case_path, job_id, status, int(returncode))
    payload["returncode"] = int(returncode)
    payload["ok"] = returncode == 0
    return payload


def watcher_attach_payload(
    case_dir: Path,
    *,
    command: list[str] | None,
    background: bool,
    log_file: str | None = None,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
    name: str = "watcher",
) -> dict[str, Any]:
    if background:
        return watcher_start_payload(
            case_dir,
            command=command,
            detached=True,
            log_file=log_file,
            env=env,
            dry_run=dry_run,
            name=name,
        )
    return watcher_run_payload(
        case_dir,
        command=command,
        env=env,
        dry_run=dry_run,
        name=name,
    )


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
    kind: str | None = None,
    signal_name: str = "TERM",
) -> dict[str, Any]:
    signal_name = signal_name.strip().upper()
    return _job_action_payload(
        case_dir,
        action="stopped",
        kind=kind,
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
    kind: str | None = None,
) -> dict[str, Any]:
    return _job_action_payload(
        case_dir,
        action="paused",
        kind=kind,
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
    kind: str | None = None,
) -> dict[str, Any]:
    return _job_action_payload(
        case_dir,
        action="resumed",
        kind=kind,
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
        return external_watch_start_payload(
            case_dir,
            command=command,
            dry_run=dry_run,
            name=name,
            detached=detached,
            log_file=log_file,
        )
    if mode == "status":
        return external_watch_status_payload(
            case_dir,
            job_id=job_id,
            name=name,
            include_all=include_all,
        )
    if mode == "attach":
        return external_watch_attach_payload(
            case_dir,
            lines=lines,
            job_id=job_id,
            name=name,
        )
    if mode == "stop":
        return external_watch_stop_payload(
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
    jobs = [_job_with_schema(case_path, job) for job in refresh_jobs(case_path)]
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


def adopt_job_payload(
    case_dir: Path,
    *,
    adopt: str,
    source_case: Path | None = None,
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    jobs = refresh_jobs(case_path)
    pid = _resolve_adopt_pid(adopt, case_path, source_case=source_case)
    for job in jobs:
        job_pid = job.get("pid")
        if not isinstance(job_pid, int) or job_pid != pid:
            continue
        if str(job.get("status")) in {"running", "paused"}:
            return {
                "case": str(case_path),
                "adopted": False,
                "reason": "already_tracked",
                "job_id": str(job.get("id")),
                "pid": pid,
                "log": str(job.get("log") or ""),
            }
    table = process_scan_service.proc_table(Path("/proc"))
    entry = table.get(pid)
    if entry is None:
        raise ValueError(f"process not found for adopt pid: {pid}")
    solver = process_scan_service.guess_solver_from_args(entry.args)
    name = solver if solver and solver != "unknown" else "solver"
    log_path = _adopt_log_path(case_path, solver)
    command = " ".join(entry.args) if entry.args else name
    job_id = register_job(
        case_path,
        name,
        pid,
        command,
        log_path,
        kind=_SOLVER_KIND,
    )
    return {
        "case": str(case_path),
        "adopted": True,
        "job_id": job_id,
        "pid": pid,
        "name": name,
        "solver": solver,
        "log": str(log_path),
    }


def _resolve_adopt_pid(
    adopt: str,
    case_path: Path,
    *,
    source_case: Path | None = None,
) -> int:
    token = str(adopt).strip()
    if not token:
        raise ValueError("adopt target is empty")
    if token.isdigit():
        pid = int(token)
        if pid <= 0:
            raise ValueError(f"invalid adopt pid: {token}")
        return pid
    source = source_case if source_case is not None else Path(token).expanduser()
    target_case = case_source_service.require_case_dir(source)
    rows = process_scan_service.scan_proc_solver_processes(
        target_case,
        None,
        tracked_pids=set(),
        include_tracked=True,
        require_case_target=True,
    )
    if not rows and target_case != case_path:
        rows = process_scan_service.scan_proc_solver_processes(
            case_path,
            None,
            tracked_pids=set(),
            include_tracked=True,
            require_case_target=True,
        )
    if not rows:
        raise ValueError(f"no running solver processes found for case: {target_case}")
    rows.sort(
        key=lambda row: (
            0 if str(row.get("role")) == "solver" else 1,
            int(row.get("pid") or 0),
        ),
    )
    pid = int(rows[0].get("pid") or 0)
    if pid <= 0:
        raise ValueError(f"invalid solver pid for case: {target_case}")
    return pid


def _adopt_log_path(case_path: Path, solver: str | None) -> Path:
    if solver and solver != "unknown":
        candidate = (case_path / f"log.{solver}").resolve()
        if candidate.is_file():
            return candidate
    logs = sorted(
        case_path.glob("log.*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if logs:
        return logs[0].resolve()
    safe = solver if solver and solver != "unknown" else "solver"
    return (case_path / f"log.{safe}").resolve()


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
        if _infer_job_kind(job) != _WATCHER_KIND:
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


def _normalize_kind_filter(kind: str | None) -> str | None:
    if kind is None:
        return None
    normalized = str(kind).strip().lower()
    if not normalized or normalized in {"all", "any"}:
        return None
    if normalized not in {_SOLVER_KIND, _WATCHER_KIND}:
        raise ValueError(f"unsupported job kind: {kind}")
    return normalized


def _infer_job_kind(job: dict[str, Any]) -> str:
    raw = str(job.get("kind") or "").strip().lower()
    if raw in {_SOLVER_KIND, _WATCHER_KIND}:
        return raw
    name = str(job.get("name") or "").strip().lower()
    if name.startswith(("watch.", "watcher")):
        return _WATCHER_KIND
    if "watch" in name and "foam" not in name:
        return _WATCHER_KIND
    return _SOLVER_KIND


def _job_with_schema(case_path: Path, job: dict[str, Any]) -> dict[str, Any]:
    row = dict(job)
    kind = _infer_job_kind(job)
    status = str(job.get("status") or "unknown")
    row["kind"] = kind
    row["case_dir"] = str(case_path)
    row["running"] = status in {"running", "paused"}
    row["detached"] = bool(job.get("detached", kind == _SOLVER_KIND))
    row["log_path"] = _job_log_path(case_path, job)
    return row


def _job_log_path(case_path: Path, job: dict[str, Any]) -> str | None:
    raw = str(job.get("log") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = case_path / path
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _resolve_watcher_command(
    case_path: Path,
    command: list[str] | None,
) -> tuple[list[str], dict[str, str], Path | None]:
    explicit = normalize_external_command(list(command or []))
    if explicit:
        return explicit, {}, None
    preset_path = case_path / "ofti.watcher"
    if not preset_path.is_file():
        return [], {}, None
    preset = _load_watcher_preset(preset_path)
    return preset.get("command", []), preset.get("env", {}), preset_path


def _load_watcher_preset(path: Path) -> dict[str, Any]:
    command: list[str] = []
    env: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {"command": command, "env": env}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed_env = _env_assignment_from_line(line)
        if parsed_env is not None:
            key, value = parsed_env
            env[key] = value
            continue
        if not command:
            cmd_text = _watcher_command_text(line)
            try:
                command = shlex.split(cmd_text)
            except ValueError:
                continue
    return {"command": command, "env": env}


def _watcher_command_text(line: str) -> str:
    if ":" not in line:
        return line
    key, value = line.split(":", 1)
    lhs = key.strip().lower()
    rhs = value.strip()
    if lhs in {"command", "cmd", "watcher", "default"} and rhs:
        return rhs
    if rhs:
        return rhs
    return line


def _env_assignment_from_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if stripped.startswith("env "):
        stripped = stripped[4:].strip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    name = key.strip()
    if not name:
        return None
    if not all(ch.isalnum() or ch == "_" for ch in name):
        return None
    return name, value


def _watcher_env(
    case_path: Path,
    *,
    watcher_id: str,
    preset_env: dict[str, str],
    extra_env: dict[str, str] | None,
) -> dict[str, str]:
    env = os.environ.copy()
    for key in _WATCHER_ENV_FORWARD_KEYS:
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["CASE_DIR"] = str(case_path)
    env["WATCHER_ID"] = watcher_id
    env.setdefault("FRAMEWORK", "ofti")
    env.update(preset_env)
    if extra_env:
        env.update(extra_env)
    return env


def _watch_settings_path(case_path: Path) -> Path:
    return case_path / ".ofti" / "watch.json"


def _load_watch_settings(case_path: Path) -> dict[str, Any]:
    path = _watch_settings_path(case_path)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return dict(data)


def _save_watch_settings(case_path: Path, settings: dict[str, Any]) -> None:
    path = _watch_settings_path(case_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, sort_keys=True))


def _watch_interval(settings: dict[str, Any]) -> float:
    value = settings.get("interval")
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return _WATCH_SETTINGS_DEFAULT_INTERVAL


def _watch_output(settings: dict[str, Any]) -> WatchOutputProfile:
    value = str(settings.get("output") or "").strip().lower()
    if value in {"brief", "detailed"}:
        return value  # type: ignore[return-value]
    return _WATCH_SETTINGS_DEFAULT_OUTPUT


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
    kind: str | None,
    run_control_fn,
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    jobs = [_job_with_schema(case_path, job) for job in refresh_jobs(case_path)]
    selected_kind = _normalize_kind_filter(kind)
    if selected_kind is not None:
        jobs = [job for job in jobs if str(job.get("kind")) == selected_kind]
    control = run_control_fn(case_path, jobs)
    payload = {
        "case": str(case_path),
        "kind": selected_kind or "any",
        "selected": control["selected"],
        "failed": control["failed"],
        action: control[action],
    }
    if "signal" in control:
        payload["signal"] = control["signal"]
    return payload
