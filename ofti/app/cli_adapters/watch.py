from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import cast

from ofti.app.cli_adapters.common import interval_with_cpu_mode, parse_env_assignments
from ofti.app.cli_adapters.run import _run_solver_with_mode
from ofti.app.cli_help import (
    _add_easy_on_cpu_flag,
    _add_table_flag,
    _help_handler,
)
from ofti.tools import table_render_service
from ofti.tools.cli_tools import watch as watch_ops


def _build_watch_parser(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    watch = groups.add_parser(
        "watch",
        help="Logs and tracked job control",
        description=(
            "Logs and tracked job control.\n"
            "For external watchers (for example scripts/oftools/ofwatch),\n"
            "run them via presets with `ofti run tool ...`."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    watch.set_defaults(func=_help_handler(watch))
    watch_sub = watch.add_subparsers(dest="command", required=False)

    jobs = watch_sub.add_parser("jobs", help="Show tracked jobs in .ofti/jobs.json")
    jobs.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    jobs.add_argument("--all", action="store_true", help="Include finished/stopped jobs")
    jobs.add_argument("--kind", choices=["solver", "watcher", "any"], default="any")
    jobs.add_argument("--output", choices=["brief", "detailed"], default=None)
    _add_table_flag(jobs)
    jobs.add_argument("--json", action="store_true")
    jobs.set_defaults(func=_watch_jobs)

    status = watch_sub.add_parser("status", help="Alias of watch jobs")
    status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    status.add_argument("--all", action="store_true", help="Include finished/stopped jobs")
    status.add_argument("--kind", choices=["solver", "watcher", "any"], default="any")
    status.add_argument("--output", choices=["brief", "detailed"], default=None)
    _add_table_flag(status)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=_watch_jobs)

    log = watch_sub.add_parser("log", help="Tail a log file (or case solver log)")
    log.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    log.add_argument("--lines", type=int, default=40)
    log.add_argument("--follow", action="store_true")
    log.add_argument("--job-id", default=None, help="Tracked job id from .ofti/jobs.json")
    log.add_argument("--case", dest="case_dir", default=Path.cwd(), type=Path)
    _add_easy_on_cpu_flag(log)
    log.add_argument("--output", choices=["brief", "detailed"], default=None)
    log.add_argument("--json", action="store_true", help="Print result as JSON")
    log.set_defaults(func=_watch_log)

    attach = watch_sub.add_parser(
        "attach",
        help="Follow logs, or launch watcher process with --watcher",
    )
    attach.add_argument("source", nargs="?", default=None, type=Path)
    attach.add_argument("--lines", type=int, default=40)
    attach.add_argument("--job-id", default=None, help="Tracked job id from .ofti/jobs.json")
    attach.add_argument(
        "--watcher",
        nargs="*",
        default=None,
        help="Start/attach watcher process command; empty uses ofti.watcher preset",
    )
    attach.add_argument(
        "--background",
        action="store_true",
        help="With --watcher, start detached and keep tracking in jobs.json",
    )
    attach.add_argument(
        "--watcher-name",
        default="watcher",
        help="Tracked watcher job name",
    )
    attach.add_argument(
        "--log-file",
        default=None,
        help="Watcher log path (relative to case or absolute)",
    )
    attach.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra environment variable for watcher process (repeatable)",
    )
    attach.add_argument("--dry-run", action="store_true", help="Show watcher launch payload only")
    attach.add_argument(
        "--adopt",
        default=None,
        help="Adopt running process by pid or case path before attach",
    )
    attach.add_argument("--case", dest="case_dir", default=Path.cwd(), type=Path)
    _add_easy_on_cpu_flag(attach)
    attach.add_argument("--output", choices=["brief", "detailed"], default=None)
    attach.add_argument("--json", action="store_true", help="Print result as JSON")
    attach.set_defaults(func=_watch_attach)

    start = watch_sub.add_parser(
        "start",
        help="Start solver or watcher in background",
    )
    start.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    start.add_argument("--case", dest="case_dir", type=Path)
    start.add_argument("--solver", default=None)
    start.add_argument("--parallel", type=int, default=0)
    start.add_argument("--mpi", default=None)
    start.add_argument(
        "--sync-subdomains",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For parallel runs, sync decomposeParDict numberOfSubdomains to --parallel",
    )
    start.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    start.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    start.add_argument(
        "--watcher",
        nargs="*",
        default=None,
        help="Start watcher command; empty uses ofti.watcher preset",
    )
    start.add_argument(
        "--watcher-name",
        default="watcher",
        help="Tracked watcher job name",
    )
    start.add_argument(
        "--no-detach",
        action="store_true",
        help="Run without session detach (default is detached background run)",
    )
    start.add_argument(
        "--log-file",
        default=None,
        help="Custom log path (relative to case or absolute)",
    )
    start.add_argument(
        "--pid-file",
        default=None,
        help="Write started PID to this file (relative to case or absolute)",
    )
    start.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra environment variable for started process (repeatable)",
    )
    start.add_argument(
        "--write-receipt",
        action="store_true",
        help="Write immutable launch receipt under ./runs/",
    )
    start.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the receipt for restore",
    )
    start.add_argument(
        "--receipt-file",
        default=None,
        type=Path,
        help="Receipt JSON path (relative paths resolve from current working directory)",
    )
    start.add_argument("--dry-run", action="store_true", help="Show launch payload only")
    start.add_argument("--json", action="store_true", help="Print result as JSON")
    start.set_defaults(func=_watch_start)

    pause = watch_sub.add_parser("pause", help="Pause tracked running jobs (SIGSTOP)")
    pause.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    pause.add_argument("--job-id", default=None)
    pause.add_argument("--name", default=None)
    pause.add_argument("--all", action="store_true")
    pause.add_argument("--kind", choices=["solver", "watcher", "any"], default="any")
    pause.add_argument("--json", action="store_true")
    pause.set_defaults(func=_watch_pause)

    resume = watch_sub.add_parser("resume", help="Resume paused tracked jobs (SIGCONT)")
    resume.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    resume.add_argument("--job-id", default=None)
    resume.add_argument("--name", default=None)
    resume.add_argument("--all", action="store_true")
    resume.add_argument("--kind", choices=["solver", "watcher", "any"], default="any")
    resume.add_argument("--json", action="store_true")
    resume.set_defaults(func=_watch_resume)

    interval = watch_sub.add_parser(
        "interval",
        help="Get/set persisted watch polling interval",
    )
    interval.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    interval.add_argument("seconds", nargs="?", type=float, default=None)
    interval.add_argument("--json", action="store_true")
    interval.set_defaults(func=_watch_interval)

    output = watch_sub.add_parser(
        "output",
        help="Get/set persisted watch output profile",
    )
    output.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    output.add_argument("--brief", action="store_true")
    output.add_argument("--detailed", action="store_true")
    output.add_argument("--json", action="store_true")
    output.set_defaults(func=_watch_output)

    run = watch_sub.add_parser("run", help="Run solver in foreground")
    run.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    run.add_argument("--solver", default=None)
    run.add_argument("--parallel", type=int, default=0)
    run.add_argument("--mpi", default=None)
    run.add_argument(
        "--sync-subdomains",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For parallel runs, sync decomposeParDict numberOfSubdomains to --parallel",
    )
    run.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    run.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    run.add_argument(
        "--write-receipt",
        action="store_true",
        help="Write immutable launch receipt under ./runs/",
    )
    run.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the receipt for restore",
    )
    run.add_argument(
        "--receipt-file",
        default=None,
        type=Path,
        help="Receipt JSON path (relative paths resolve from current working directory)",
    )
    run.add_argument("--json", action="store_true", help="Print result as JSON")
    run.set_defaults(func=_watch_run)

    stop = watch_sub.add_parser("stop", help="Stop tracked running jobs")
    stop.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    stop.add_argument("--job-id", default=None)
    stop.add_argument("--name", default=None)
    stop.add_argument("--all", action="store_true")
    stop.add_argument("--kind", choices=["solver", "watcher", "any"], default="any")
    stop.add_argument(
        "--signal",
        default="TERM",
        choices=["TERM", "INT", "QUIT", "KILL"],
        help="Signal used to stop job(s); TERM is gentle and default",
    )
    stop.add_argument("--json", action="store_true")
    stop.set_defaults(func=_watch_stop)

    external = watch_sub.add_parser(
        "external",
        help="External watcher lifecycle: run/start/status/attach/stop",
    )
    external.add_argument("--case", dest="case_dir", default=Path.cwd(), type=Path)
    external.add_argument("--start", action="store_true", help="Start watcher in background")
    external.add_argument(
        "--status",
        action="store_true",
        help="Show tracked external watcher jobs",
    )
    external.add_argument(
        "--attach",
        action="store_true",
        help="Tail tracked external watcher log",
    )
    external.add_argument(
        "--stop",
        action="store_true",
        help="Stop tracked external watcher job(s)",
    )
    external.add_argument("--job-id", default=None, help="Tracked external watcher job id")
    external.add_argument(
        "--name",
        default="watch.external",
        help="External watcher job name/prefix",
    )
    external.add_argument(
        "--all",
        action="store_true",
        help="Apply to all matching external watcher jobs",
    )
    external.add_argument("--lines", type=int, default=40, help="Tail lines for --attach")
    external.add_argument("--follow", action="store_true", help="Follow mode for --attach")
    external.add_argument(
        "--interval",
        type=float,
        default=0.25,
        help="Polling interval for --follow",
    )
    external.add_argument(
        "--log-file",
        default=None,
        help="Log file for --start (relative to case or absolute)",
    )
    external.add_argument(
        "--no-detach",
        action="store_true",
        help="Do not detach session for --start",
    )
    external.add_argument(
        "--signal",
        default="TERM",
        choices=["TERM", "INT", "QUIT", "KILL"],
        help="Signal used by --stop (TERM is default)",
    )
    external.add_argument("--dry-run", action="store_true")
    _add_easy_on_cpu_flag(external)
    external.add_argument("--output", choices=["brief", "detailed"], default=None)
    external.add_argument("--json", action="store_true")
    external.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="External watcher command and arguments (use '--' before command)",
    )
    external.set_defaults(func=_watch_external)

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
        for job in payload["jobs"]:
            print(
                f"- id={job.get('id')} kind={job.get('kind')} pid={job.get('pid')} "
                f"status={job.get('status')}",
            )
        return 0
    print(f"case={payload['case']}")
    print(f"kind={payload.get('kind', 'any')}")
    if not payload["jobs"]:
        print("No tracked jobs.")
        return 0
    for job in payload["jobs"]:
        print(
            f"{job.get('name', 'job')} kind={job.get('kind', 'unknown')} "
            f"pid={job.get('pid', '?')} status={job.get('status', 'unknown')}",
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
    interval = interval_with_cpu_mode(args, base_interval)
    return _follow_log_path(Path(payload["log"]), interval=interval)

def _watch_attach(args: argparse.Namespace) -> int:
    watcher_raw = getattr(args, "watcher", None)
    if watcher_raw is not None:
        return _watch_attach_watcher(args, list(watcher_raw))

    job_id = args.job_id
    if getattr(args, "adopt", None):
        adopted = _watch_adopt_payload(args)
        if adopted is None:
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

def _watch_attach_watcher(args: argparse.Namespace, watcher_raw: list[str]) -> int:
    if getattr(args, "adopt", None):
        print("ofti: --adopt cannot be used with --watcher", file=sys.stderr)
        return 2
    try:
        extra_env = parse_env_assignments(getattr(args, "env", []))
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 2
    payload = watch_ops.watcher_attach_payload(
        args.case_dir,
        command=watcher_raw,
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
    return _print_watch_external_attach(args, payload)

def _watch_adopt_payload(args: argparse.Namespace) -> dict[str, object] | None:
    try:
        return watch_ops.adopt_job_payload(
            args.case_dir,
            adopt=str(args.adopt),
        )
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return None

def _watch_start(args: argparse.Namespace) -> int:
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
            watcher_raw = []
    if watcher_raw is not None:
        try:
            extra_env = parse_env_assignments(getattr(args, "env", []))
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
    return _run_solver_with_mode(args, background=True)

def _watch_run(args: argparse.Namespace) -> int:
    return _run_solver_with_mode(args, background=False)

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
            print(f"- id={row['id']} pid={row['pid']} name={row['name']}")
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
    interval = interval_with_cpu_mode(args, interval)
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
    _add_watch_json_jobs(base, payload)
    _add_watch_json_log(base, payload)
    _copy_watch_json_scalars(
        base,
        payload,
        ("count", "selected", "signal", "pid", "job_id", "kind", "detached", "running", "log_path"),
    )
    return base

def _add_watch_json_jobs(base: dict[str, object], payload: dict[str, object]) -> None:
    if "jobs" not in payload:
        return
    jobs = cast("list[dict[str, object]]", payload.get("jobs", []))
    base["items"] = [
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

def _add_watch_json_log(base: dict[str, object], payload: dict[str, object]) -> None:
    if "log" not in payload:
        return
    lines = cast("list[str]", payload.get("lines", []))
    base["log"] = payload.get("log")
    base["line_count"] = len(lines)
    base["lines"] = lines

def _copy_watch_json_scalars(
    base: dict[str, object],
    payload: dict[str, object],
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        if key in payload:
            base[key] = payload.get(key)

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
