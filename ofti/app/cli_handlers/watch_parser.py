from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Handler = Callable[[argparse.Namespace], int]


@dataclass(frozen=True)
class WatchHandlers:
    jobs: Handler
    cases: Handler
    log: Handler
    attach: Handler
    start: Handler
    pause: Handler
    resume: Handler
    interval: Handler
    output: Handler
    run: Handler
    stop: Handler
    external: Handler


def _help_handler(parser: argparse.ArgumentParser) -> Handler:
    def _show_help(_args: argparse.Namespace) -> int:
        parser.print_help()
        return 0

    return _show_help


def _add_easy_on_cpu_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--easy-on-cpu",
        action="store_true",
        help="Reduce CPU load with bounded log reads (can be combined with --fast/--full)",
    )
    parser.add_argument(
        "--lightweight",
        dest="easy_on_cpu",
        action="store_true",
        help=argparse.SUPPRESS,
    )


def _add_table_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--table",
        action="store_true",
        help="Print aligned human-readable tables",
    )


def add_parser(
    groups: argparse._SubParsersAction[argparse.ArgumentParser],
    handlers: WatchHandlers,
) -> None:
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
    jobs.set_defaults(func=handlers.jobs)

    cases = watch_sub.add_parser(
        "cases",
        help="Monitor a live case set as a read-only grid",
        description=(
            "Show a read-only live cases monitor for explicit cases or for "
            "cases discovered under --set/--glob."
        ),
    )
    cases.add_argument("cases", nargs="*", type=Path, help="Explicit case directories")
    cases.add_argument(
        "--set",
        dest="set_dir",
        default=Path.cwd(),
        type=Path,
        help="Case-set root used when explicit cases are omitted",
    )
    cases.add_argument("--glob", default="*", help="Case directory glob under --set")
    cases.add_argument(
        "--summary-csv",
        default=None,
        type=Path,
        help="Read case paths from a campaign summary CSV",
    )
    cases_mode = cases.add_mutually_exclusive_group()
    cases_mode.add_argument("--fast", action="store_true", help="Use lightweight status parsing")
    cases_mode.add_argument("--full", action="store_true", help="Parse full logs (slower)")
    _add_easy_on_cpu_flag(cases)
    cases.add_argument(
        "--tail-bytes",
        type=int,
        default=None,
        help="Max solver log bytes to parse",
    )
    cases.add_argument("--follow", action="store_true", help="Refresh until interrupted")
    cases.add_argument("--interval", type=float, default=2.0, help="Refresh interval for --follow")
    cases.add_argument(
        "--sort",
        choices=["case", "state", "latest", "eta", "jobs"],
        default="state",
        help="Sort case grid rows",
    )
    cases.add_argument("--group-state", action="store_true", help="Group case grid rows by state")
    _add_table_flag(cases)
    cases.add_argument("--json", action="store_true", help="Print result as JSON")
    cases.set_defaults(func=handlers.cases)

    status = watch_sub.add_parser("status", help="Alias of watch jobs")
    status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    status.add_argument("--all", action="store_true", help="Include finished/stopped jobs")
    status.add_argument("--kind", choices=["solver", "watcher", "any"], default="any")
    status.add_argument("--output", choices=["brief", "detailed"], default=None)
    _add_table_flag(status)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=handlers.jobs)

    log = watch_sub.add_parser("log", help="Tail a log file (or case solver log)")
    log.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    log.add_argument("--lines", type=int, default=40)
    log.add_argument("--follow", action="store_true")
    log.add_argument("--job-id", default=None, help="Tracked job id from .ofti/jobs.json")
    log.add_argument("--case", dest="case_dir", default=Path.cwd(), type=Path)
    _add_easy_on_cpu_flag(log)
    log.add_argument("--output", choices=["brief", "detailed"], default=None)
    log.add_argument("--json", action="store_true", help="Print result as JSON")
    log.set_defaults(func=handlers.log)

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
    attach.set_defaults(func=handlers.attach)

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
        "--write-manifest",
        dest="write_receipt",
        action="store_true",
        help="Write immutable launch manifest under ./runs/",
    )
    start.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the receipt for restore",
    )
    start.add_argument(
        "--receipt-file",
        "--manifest-file",
        dest="receipt_file",
        default=None,
        type=Path,
        help="Manifest/receipt JSON path (relative paths resolve from current working directory)",
    )
    start.add_argument("--dry-run", action="store_true", help="Show launch payload only")
    start.add_argument("--json", action="store_true", help="Print result as JSON")
    start.set_defaults(func=handlers.start)

    pause = watch_sub.add_parser("pause", help="Pause tracked running jobs (SIGSTOP)")
    pause.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    pause.add_argument("--job-id", default=None)
    pause.add_argument("--name", default=None)
    pause.add_argument("--all", action="store_true")
    pause.add_argument("--kind", choices=["solver", "watcher", "any"], default="any")
    pause.add_argument("--json", action="store_true")
    pause.set_defaults(func=handlers.pause)

    resume = watch_sub.add_parser("resume", help="Resume paused tracked jobs (SIGCONT)")
    resume.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    resume.add_argument("--job-id", default=None)
    resume.add_argument("--name", default=None)
    resume.add_argument("--all", action="store_true")
    resume.add_argument("--kind", choices=["solver", "watcher", "any"], default="any")
    resume.add_argument("--json", action="store_true")
    resume.set_defaults(func=handlers.resume)

    interval = watch_sub.add_parser(
        "interval",
        help="Get/set persisted watch polling interval",
    )
    interval.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    interval.add_argument("seconds", nargs="?", type=float, default=None)
    interval.add_argument("--json", action="store_true")
    interval.set_defaults(func=handlers.interval)

    output = watch_sub.add_parser(
        "output",
        help="Get/set persisted watch output profile",
    )
    output.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    output.add_argument("--brief", action="store_true")
    output.add_argument("--detailed", action="store_true")
    output.add_argument("--json", action="store_true")
    output.set_defaults(func=handlers.output)

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
        "--write-manifest",
        dest="write_receipt",
        action="store_true",
        help="Write immutable launch manifest under ./runs/",
    )
    run.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the receipt for restore",
    )
    run.add_argument(
        "--receipt-file",
        "--manifest-file",
        dest="receipt_file",
        default=None,
        type=Path,
        help="Manifest/receipt JSON path (relative paths resolve from current working directory)",
    )
    run.add_argument("--json", action="store_true", help="Print result as JSON")
    run.set_defaults(func=handlers.run)

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
    stop.set_defaults(func=handlers.stop)

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
    external.set_defaults(func=handlers.external)
