from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import cast

from ofti.app.cli_adapters import run as run_cli
from ofti.app.cli_adapters.watch_cases import (  # noqa: F401
    _none_last,
    _watch_case_sort_key,
    _watch_cases,
    _watch_cases_payload,
)
from ofti.app.cli_adapters.watch_parser import WatchHandlers, add_parser  # noqa: F401
from ofti.tools import table_render_service
from ofti.tools.cli_tools import watch as watch_ops

_EASY_ON_CPU_TAIL_BYTES = 256 * 1024
_EASY_ON_CPU_MIN_POLL_INTERVAL = 1.0


def _watch_use_easy_on_cpu_mode(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "easy_on_cpu", False))


def _tail_bytes_with_cpu_mode(args: argparse.Namespace) -> int | None:
    explicit = getattr(args, "tail_bytes", None)
    if explicit is not None:
        return int(explicit)
    if _watch_use_easy_on_cpu_mode(args):
        return _EASY_ON_CPU_TAIL_BYTES
    return None


def _interval_with_cpu_mode(args: argparse.Namespace, interval: float) -> float:
    if not _watch_use_easy_on_cpu_mode(args):
        return interval
    return max(float(interval), _EASY_ON_CPU_MIN_POLL_INTERVAL)


def _watch_jobs(args: argparse.Namespace) -> int:
    payload = watch_ops.jobs_payload(
        args.case_dir,
        include_all=bool(args.all),
        kind=str(getattr(args, "kind", "any")),
    )
    profile = _watch_profile(args.case_dir, getattr(args, "output", None))
    if args.json:
        print(
            json.dumps(
                _watch_json_payload("jobs", payload, profile=profile),
                indent=2,
                sort_keys=True,
            ),
        )
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.jobs_payload_table_lines(payload)))
        return 0
    if profile == "brief":
        print(f"case={payload['case']} kind={payload.get('kind', 'any')} count={payload['count']}")
        for job in payload.get("runs", payload["jobs"]):
            print(
                f"- id={job.get('id')} kind={job.get('kind')} pid={job.get('pid')} "
                f"status={job.get('status')} source={job.get('source', 'registry')}",
            )
        return 0
    print(f"case={payload['case']}")
    print(f"kind={payload.get('kind', 'any')}")
    if not payload["jobs"]:
        print("No tracked jobs.")
        return 0
    for job in payload.get("runs", payload["jobs"]):
        print(
            f"{job.get('name', 'job')} kind={job.get('kind', 'unknown')} "
            f"pid={job.get('pid', '?')} status={job.get('status', 'unknown')} "
            f"source={job.get('source', 'registry')}",
        )
    return 0




def _watch_log(args: argparse.Namespace) -> int:
    if args.follow and args.json:
        print("ofti: --json cannot be used with --follow", file=sys.stderr)
        return 2
    try:
        if args.job_id:
            payload = watch_ops.log_tail_payload_for_job(
                args.case_dir,
                job_id=str(args.job_id),
                lines=int(args.lines),
            )
        else:
            payload = watch_ops.log_tail_payload(args.source, lines=int(args.lines))
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    profile = _watch_profile(args.case_dir, getattr(args, "output", None))
    if args.json:
        print(
            json.dumps(
                _watch_json_payload("log", payload, profile=profile),
                indent=2,
                sort_keys=True,
            ),
        )
        return 0
    if profile == "brief":
        print(f"log={payload['log']} lines={len(payload['lines'])}")
    else:
        for line in payload["lines"]:
            print(line)
    if not args.follow:
        return 0

    base_interval = 0.25
    with suppress(Exception):
        base_interval = watch_ops.effective_interval(args.case_dir)
    interval = _interval_with_cpu_mode(args, base_interval)
    return _follow_log_path(Path(payload["log"]), interval=interval)


def _watch_attach(args: argparse.Namespace) -> int:
    watcher_raw = getattr(args, "watcher", None)
    if watcher_raw is not None:
        return _watch_attach_watcher(args, list(watcher_raw))

    job_id = args.job_id
    if getattr(args, "adopt", None):
        try:
            adopted = watch_ops.adopt_job_payload(
                args.case_dir,
                adopt=str(args.adopt),
            )
        except ValueError as exc:
            print(f"ofti: {exc}", file=sys.stderr)
            return 1
        job_id = adopted.get("job_id")
        if args.json:
            print(
                json.dumps(
                    _watch_json_payload("adopt", adopted, profile="detailed"),
                    indent=2,
                    sort_keys=True,
                ),
            )
            return 0
    attached_args = argparse.Namespace(
        source=args.source if args.source is not None else args.case_dir,
        lines=args.lines,
        follow=True,
        job_id=job_id,
        case_dir=args.case_dir,
        easy_on_cpu=bool(getattr(args, "easy_on_cpu", False)),
        output=getattr(args, "output", None),
        json=args.json,
    )
    return _watch_log(attached_args)


def _watch_attach_watcher(args: argparse.Namespace, watcher_raw: list[object]) -> int:
    if getattr(args, "adopt", None):
        print("ofti: --adopt cannot be used with --watcher", file=sys.stderr)
        return 2
    try:
        extra_env = run_cli._parse_env_assignments(getattr(args, "env", []))
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 2
    payload = watch_ops.watcher_attach_payload(
        args.case_dir,
        command=list(watcher_raw),
        background=bool(getattr(args, "background", False)),
        log_file=getattr(args, "log_file", None),
        env=extra_env,
        dry_run=bool(getattr(args, "dry_run", False)),
        name=str(getattr(args, "watcher_name", "watcher")),
    )
    if args.json:
        print(
            json.dumps(
                _watch_json_payload("attach.watcher", payload, profile="detailed"),
                indent=2,
                sort_keys=True,
            ),
        )
        return 0 if bool(payload.get("ok", True)) else 1
    print(f"case={payload['case']}")
    print(f"kind={payload.get('kind', 'watcher')}")
    print(f"name={payload.get('name')}")
    print(f"command={payload.get('command')}")
    if payload.get("dry_run"):
        print("dry_run=True")
        return 0
    if payload.get("log_path"):
        print(f"log_path={payload.get('log_path')}")
    if payload.get("pid") is not None:
        print(f"pid={payload.get('pid')}")
    if payload.get("job_id") is not None:
        print(f"job_id={payload.get('job_id')}")
    if payload.get("returncode") is not None:
        print(f"returncode={payload.get('returncode')}")
    return 0 if bool(payload.get("ok", True)) else 1


def _watch_start(args: argparse.Namespace) -> int:
    watcher_raw = _default_watcher_command(args)
    if watcher_raw is not None:
        return _watch_start_watcher(args, list(watcher_raw))
    return run_cli._run_solver_with_mode(args, background=True)


def _default_watcher_command(args: argparse.Namespace) -> object:
    watcher_raw = getattr(args, "watcher", None)
    if (
        watcher_raw is None
        and not getattr(args, "solver", None)
        and int(getattr(args, "parallel", 0) or 0) <= 0
        and getattr(args, "mpi", None) is None
    ):
        try:
            preset = watch_ops.watcher_preset_payload(args.case_dir)
        except Exception:
            preset = {"found": False}
        if bool(preset.get("found")):
            return []
    return watcher_raw


def _watch_start_watcher(args: argparse.Namespace, watcher_raw: list[object]) -> int:
    try:
        extra_env = run_cli._parse_env_assignments(getattr(args, "env", []))
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 2
    payload = watch_ops.watcher_start_payload(
        args.case_dir,
        command=list(watcher_raw),
        detached=not bool(getattr(args, "no_detach", False)),
        log_file=getattr(args, "log_file", None),
        env=extra_env,
        dry_run=bool(getattr(args, "dry_run", False)),
        name=str(getattr(args, "watcher_name", "watcher")),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok", True)) else 1
    print(f"case={payload['case']}")
    print(f"kind={payload.get('kind', 'watcher')}")
    print(f"name={payload['name']}")
    print(f"command={payload['command']}")
    print(f"log_path={payload.get('log_path')}")
    if payload.get("dry_run"):
        print("dry_run=True")
        return 0
    print(f"pid={payload.get('pid')}")
    print(f"job_id={payload.get('job_id')}")
    return 0 if bool(payload.get("ok", True)) else 1


def _watch_run(args: argparse.Namespace) -> int:
    return run_cli._run_solver_with_mode(args, background=False)



def _watch_stop(args: argparse.Namespace) -> int:
    signal_name = str(getattr(args, "signal", "TERM")).upper()
    payload = watch_ops.stop_payload(
        args.case_dir,
        job_id=args.job_id,
        name=args.name,
        all_jobs=bool(args.all),
        kind=str(getattr(args, "kind", "any")),
        signal_name=signal_name,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not payload["failed"] else 1
    print(f"case={payload['case']}")
    print(f"signal={payload.get('signal', signal_name)}")
    print(f"selected={payload['selected']}")
    if payload["stopped"]:
        print("stopped:")
        for row in payload["stopped"]:
            method = row.get("method", "process")
            pgid = f" pgid={row['pgid']}" if row.get("pgid") is not None else ""
            print(f"- id={row['id']} pid={row['pid']}{pgid} method={method} name={row['name']}")
    if payload["failed"]:
        print("failed:")
        for row in payload["failed"]:
            print(f"- id={row.get('id')} pid={row.get('pid')} error={row['error']}")
    return 0 if not payload["failed"] else 1


def _watch_pause(args: argparse.Namespace) -> int:
    payload = watch_ops.pause_payload(
        args.case_dir,
        job_id=args.job_id,
        name=args.name,
        all_jobs=bool(args.all),
        kind=str(getattr(args, "kind", "any")),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not payload["failed"] else 1
    print(f"case={payload['case']}")
    print(f"selected={payload['selected']}")
    if payload["paused"]:
        print("paused:")
        for row in payload["paused"]:
            print(f"- id={row['id']} pid={row['pid']} name={row['name']}")
    if payload["failed"]:
        print("failed:")
        for row in payload["failed"]:
            print(f"- id={row.get('id')} pid={row.get('pid')} error={row['error']}")
    return 0 if not payload["failed"] else 1


def _watch_resume(args: argparse.Namespace) -> int:
    payload = watch_ops.resume_payload(
        args.case_dir,
        job_id=args.job_id,
        name=args.name,
        all_jobs=bool(args.all),
        kind=str(getattr(args, "kind", "any")),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not payload["failed"] else 1
    print(f"case={payload['case']}")
    print(f"selected={payload['selected']}")
    if payload["resumed"]:
        print("resumed:")
        for row in payload["resumed"]:
            print(f"- id={row['id']} pid={row['pid']} name={row['name']}")
    if payload["failed"]:
        print("failed:")
        for row in payload["failed"]:
            print(f"- id={row.get('id')} pid={row.get('pid')} error={row['error']}")
    return 0 if not payload["failed"] else 1


def _watch_interval(args: argparse.Namespace) -> int:
    payload = watch_ops.interval_payload(args.case_dir, seconds=args.seconds)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"effective={payload['effective']}")
    print(f"changed={payload['changed']}")
    if payload["requested"] is not None:
        print(f"requested={payload['requested']}")
    print(f"settings={payload['settings_path']}")
    return 0


def _watch_output(args: argparse.Namespace) -> int:
    brief = bool(getattr(args, "brief", False))
    detailed = bool(getattr(args, "detailed", False))
    if brief and detailed:
        print("ofti: choose only one of --brief/--detailed", file=sys.stderr)
        return 2
    profile = "brief" if brief else "detailed" if detailed else None
    payload = watch_ops.output_profile_payload(args.case_dir, profile=profile)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"effective={payload['effective']}")
    print(f"changed={payload['changed']}")
    if payload["requested"] is not None:
        print(f"requested={payload['requested']}")
    print(f"settings={payload['settings_path']}")
    return 0


def _watch_external(args: argparse.Namespace) -> int:
    mode = watch_ops.external_watch_mode(
        start=bool(getattr(args, "start", False)),
        status=bool(getattr(args, "status", False)),
        attach=bool(getattr(args, "attach", False)),
        stop=bool(getattr(args, "stop", False)),
    )
    if mode is None:
        print("ofti: choose only one of --start/--status/--attach/--stop", file=sys.stderr)
        return 2
    command = watch_ops.normalize_external_command(list(args.command))
    if mode in {"run", "start"} and not command and not bool(getattr(args, "dry_run", False)):
        print("ofti: external command is required", file=sys.stderr)
        return 2
    payload = watch_ops.external_watch_mode_payload(
        args.case_dir,
        mode=mode,
        command=command,
        dry_run=bool(getattr(args, "dry_run", False)),
        name=str(getattr(args, "name", "watch.external")),
        detached=not bool(getattr(args, "no_detach", False)),
        log_file=getattr(args, "log_file", None),
        job_id=getattr(args, "job_id", None),
        include_all=bool(getattr(args, "all", False)),
        all_jobs=bool(getattr(args, "all", False)),
        lines=int(getattr(args, "lines", 40)),
        signal_name=str(getattr(args, "signal", "TERM")),
    )
    return _watch_external_render(args, mode, payload)


def _watch_external_render(
    args: argparse.Namespace,
    mode: str,
    payload: dict[str, object],
) -> int:
    profile = _watch_profile(args.case_dir, getattr(args, "output", None))
    if args.json:
        print(
            json.dumps(
                _watch_json_payload(f"external.{mode}", payload, profile=profile),
                indent=2,
                sort_keys=True,
            ),
        )
        return _watch_external_json_exit(mode, payload)
    handlers: dict[str, Callable[[dict[str, object]], int]] = {
        "status": _print_watch_external_status,
        "attach": lambda data: _print_watch_external_attach(args, data),
        "stop": _print_watch_external_stop,
        "start": _print_watch_external_start,
    }
    handler = handlers.get(mode, _print_watch_external_run)
    return handler(payload)


def _watch_external_json_exit(mode: str, payload: dict[str, object]) -> int:
    if mode == "stop":
        failed = payload.get("failed")
        return 0 if not failed else 1
    if mode in {"status", "attach"}:
        return 0
    return 0 if bool(payload.get("ok", True)) else 1


def _print_watch_external_status(payload: dict[str, object]) -> int:
    print(f"case={payload['case']}")
    print(f"name={payload['name']}")
    print(f"count={payload['count']}")
    jobs = cast("list[dict[str, object]]", payload.get("jobs", []))
    for job in jobs:
        print(
            f"- id={job.get('id')} name={job.get('name')} pid={job.get('pid')} "
            f"status={job.get('status')}",
        )
    return 0


def _print_watch_external_attach(args: argparse.Namespace, payload: dict[str, object]) -> int:
    profile = _watch_profile(args.case_dir, getattr(args, "output", None))
    lines = cast("list[str]", payload.get("lines", []))
    if profile == "brief":
        print(f"log={payload.get('log')} lines={len(lines)}")
    else:
        for line in lines:
            print(line)
    if not args.follow:
        return 0
    interval = float(args.interval)
    if interval <= 0:
        interval = watch_ops.effective_interval(args.case_dir)
    interval = _interval_with_cpu_mode(args, interval)
    return _follow_log_path(Path(str(payload["log"])), interval=interval)


def _print_watch_external_stop(payload: dict[str, object]) -> int:
    print(f"case={payload['case']}")
    print(f"name={payload['name']}")
    print(f"signal={payload['signal']}")
    print(f"selected={payload['selected']}")
    stopped = cast("list[dict[str, object]]", payload.get("stopped", []))
    failed = cast("list[dict[str, object]]", payload.get("failed", []))
    if stopped:
        print("stopped:")
        for row in stopped:
            print(f"- id={row.get('id')} pid={row.get('pid')} name={row.get('name')}")
    if failed:
        print("failed:")
        for row in failed:
            print(f"- id={row.get('id')} pid={row.get('pid')} error={row.get('error')}")
    return 0 if not failed else 1


def _print_watch_external_start(payload: dict[str, object]) -> int:
    print(f"case={payload['case']}")
    print(f"name={payload['name']}")
    print(f"command={payload['command']}")
    print(f"log_path={payload['log_path']}")
    if payload.get("dry_run"):
        print("dry_run=True")
        return 0
    print(f"pid={payload.get('pid')}")
    print(f"job_id={payload.get('job_id')}")
    return 0 if bool(payload.get("ok", True)) else 1


def _print_watch_external_run(payload: dict[str, object]) -> int:
    print(f"case={payload['case']}")
    print(f"command={payload['command']}")
    if payload.get("dry_run"):
        print("dry_run=True")
        return 0
    print(f"pid={payload.get('pid')}")
    print(f"returncode={payload.get('returncode')}")
    return 0 if bool(payload.get("ok", True)) else 1


def _watch_profile(case_dir: Path, explicit: str | None) -> str:
    if explicit in {"brief", "detailed"}:
        return explicit
    try:
        return str(watch_ops.effective_output_profile(case_dir))
    except Exception:
        return "detailed"


def _watch_json_payload(
    command: str,
    payload: dict[str, object],
    *,
    profile: str,
) -> dict[str, object]:
    if profile == "detailed":
        return payload
    base: dict[str, object] = {
        "schema": "ofti.watch.v1",
        "command": command,
        "profile": "brief",
        "case": payload.get("case"),
        "ok": payload.get("ok", True),
    }
    _copy_present_keys(
        base,
        payload,
        ("count", "selected", "signal", "pid", "job_id", "kind", "detached", "running", "log_path"),
    )
    _add_brief_jobs(base, payload)
    _add_brief_log(base, payload)
    return base


def _copy_present_keys(
    target: dict[str, object],
    source: dict[str, object],
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        if key in source:
            target[key] = source.get(key)


def _add_brief_jobs(target: dict[str, object], payload: dict[str, object]) -> None:
    if "jobs" not in payload:
        return
    jobs = cast("list[dict[str, object]]", payload.get("jobs", []))
    target["items"] = [
        {
            "id": job.get("id"),
            "name": job.get("name"),
            "kind": job.get("kind"),
            "case_dir": job.get("case_dir"),
            "pid": job.get("pid"),
            "status": job.get("status"),
            "running": job.get("running"),
            "detached": job.get("detached"),
            "log_path": job.get("log_path"),
        }
        for job in jobs
    ]


def _add_brief_log(target: dict[str, object], payload: dict[str, object]) -> None:
    if "log" not in payload:
        return
    lines = cast("list[str]", payload.get("lines", []))
    target["log"] = payload.get("log")
    target["line_count"] = len(lines)
    target["lines"] = lines


def _follow_log_path(log_path: Path, *, interval: float) -> int:
    sleep_interval = max(0.05, float(interval))
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(0, 2)
            while True:
                line = handle.readline()
                if line:
                    print(line.rstrip("\n"), flush=True)
                    continue
                time.sleep(sleep_interval)
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"Failed to follow {log_path}: {exc}", file=sys.stderr)
        return 1
