from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from textwrap import dedent
from typing import cast

from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import plot as plot_ops
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.cli_tools import watch as watch_ops

Handler = Callable[[argparse.Namespace], int]


def _help_handler(parser: argparse.ArgumentParser) -> Handler:
    def _show_help(_args: argparse.Namespace) -> int:
        parser.print_help()
        return 0

    return _show_help


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofti",
        description=(
            "Non-interactive OFTI utilities.\n"
            "Use --json on commands for machine-readable output."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent(
            """\
            Examples:
              ofti knife preflight CASE
              ofti watch log CASE --lines 80
              ofti run tool --list --case CASE
              ofti run tool blockMesh --case CASE --background
              ofti run solver CASE --parallel 8 --dry-run
            """,
        ),
    )
    parser.set_defaults(func=_help_handler(parser))
    groups = parser.add_subparsers(dest="group", required=False)

    _build_knife_parser(groups)
    _build_plot_parser(groups)
    _build_watch_parser(groups)
    _build_run_parser(groups)
    return parser


def _build_knife_parser(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    knife = groups.add_parser(
        "knife",
        help="Case inspection and quick edits",
        description="Case inspection and quick edits.",
    )
    knife.set_defaults(func=_help_handler(knife))
    knife_sub = knife.add_subparsers(dest="command", required=False)

    doctor = knife_sub.add_parser("doctor", help="Run case doctor checks")
    doctor.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=_knife_doctor)

    preflight = knife_sub.add_parser("preflight", help="Check basic case/run prerequisites")
    preflight.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    preflight.add_argument("--json", action="store_true")
    preflight.set_defaults(func=_knife_preflight)

    compare = knife_sub.add_parser("compare", help="Compare dictionary keys between two cases")
    compare.add_argument("left_case", type=Path)
    compare.add_argument("right_case", type=Path)
    compare.add_argument("--json", action="store_true")
    compare.set_defaults(func=_knife_compare)

    copy = knife_sub.add_parser(
        "copy",
        help="Copy case to destination (skip runtime artifacts by default)",
    )
    copy.add_argument("destination", type=Path)
    copy.add_argument("--case", dest="case_dir", default=Path.cwd(), type=Path)
    copy.add_argument(
        "--with-trash",
        action="store_true",
        help="Include runtime artifacts (log.*, processor*, time dirs, postProcessing)",
    )
    copy.add_argument(
        "--drop-mesh",
        action="store_true",
        help="Also skip constant/polyMesh in destination",
    )
    copy.add_argument("--json", action="store_true")
    copy.set_defaults(func=_knife_copy)

    initials = knife_sub.add_parser(
        "initials",
        help="Show initial internal fields and boundary conditions",
    )
    initials.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    initials.add_argument("--json", action="store_true")
    initials.set_defaults(func=_knife_initials)

    status = knife_sub.add_parser("status", help="Show solver/job status for a case")
    status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    status.add_argument(
        "--lightweight",
        action="store_true",
        help="Tail-only bounded log read for fast polling",
    )
    status.add_argument(
        "--tail-bytes",
        type=int,
        default=None,
        help="Max log bytes to parse (default: auto in --lightweight mode)",
    )
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=_knife_status)

    current = knife_sub.add_parser("current", help="Show currently tracked running jobs")
    current.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    current.add_argument("--json", action="store_true")
    current.set_defaults(func=_knife_current)

    case_status = knife_sub.add_parser("case-status", help="Alias of knife status")
    case_status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    case_status.add_argument(
        "--lightweight",
        action="store_true",
        help="Tail-only bounded log read for fast polling",
    )
    case_status.add_argument(
        "--tail-bytes",
        type=int,
        default=None,
        help="Max log bytes to parse (default: auto in --lightweight mode)",
    )
    case_status.add_argument("--json", action="store_true")
    case_status.set_defaults(func=_knife_status)

    set_cmd = knife_sub.add_parser("set", help="Set dictionary entry value")
    set_cmd.add_argument("case_dir", type=Path)
    set_cmd.add_argument("file", help="Dictionary path relative to case, e.g. system/controlDict")
    set_cmd.add_argument("key", help="Entry key, e.g. application")
    set_cmd.add_argument("value", nargs="+", help="Entry value text")
    set_cmd.add_argument("--json", action="store_true", help="Print result as JSON")
    set_cmd.set_defaults(func=_knife_set)

    launch = knife_sub.add_parser("launch", help="Alias of watch start")
    launch.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    launch.add_argument("--solver", default=None)
    launch.add_argument("--parallel", type=int, default=0)
    launch.add_argument("--mpi", default=None)
    launch.add_argument("--json", action="store_true", help="Print result as JSON")
    launch.set_defaults(func=_watch_start)

    run = knife_sub.add_parser("run", help="Alias of watch start")
    run.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    run.add_argument("--solver", default=None)
    run.add_argument("--parallel", type=int, default=0)
    run.add_argument("--mpi", default=None)
    run.add_argument("--json", action="store_true", help="Print result as JSON")
    run.set_defaults(func=_watch_start)

    stop = knife_sub.add_parser("stop", help="Alias of watch stop")
    stop.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    stop.add_argument("--job-id", default=None)
    stop.add_argument("--name", default=None)
    stop.add_argument("--all", action="store_true")
    stop.add_argument(
        "--signal",
        default="TERM",
        choices=["TERM", "INT", "QUIT", "KILL"],
        help="Signal used to stop job(s); TERM is gentle and default",
    )
    stop.add_argument("--json", action="store_true")
    stop.set_defaults(func=_watch_stop)

    pause = knife_sub.add_parser("pause", help="Alias of watch pause")
    pause.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    pause.add_argument("--job-id", default=None)
    pause.add_argument("--name", default=None)
    pause.add_argument("--all", action="store_true")
    pause.add_argument("--json", action="store_true")
    pause.set_defaults(func=_watch_pause)

    resume = knife_sub.add_parser("resume", help="Alias of watch resume")
    resume.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    resume.add_argument("--job-id", default=None)
    resume.add_argument("--name", default=None)
    resume.add_argument("--all", action="store_true")
    resume.add_argument("--json", action="store_true")
    resume.set_defaults(func=_watch_resume)

    converge = knife_sub.add_parser(
        "converge",
        help="Post-check convergence signals from solver logs",
    )
    converge.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    converge.add_argument(
        "--strict",
        action="store_true",
        help="Require shock+drag+mass checks to pass",
    )
    converge.add_argument("--shock-drift-limit", type=float, default=0.02)
    converge.add_argument("--drag-band-limit", type=float, default=0.02)
    converge.add_argument("--mass-limit", type=float, default=1e-4)
    converge.add_argument("--json", action="store_true")
    converge.set_defaults(func=_knife_converge)

    stability = knife_sub.add_parser(
        "stability",
        help="Generic windowed stability check for scalar log series",
    )
    stability.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    stability.add_argument(
        "--pattern",
        required=True,
        help="Regex with named group 'value' (or first group) for scalar extraction",
    )
    stability.add_argument("--tolerance", type=float, required=True)
    stability.add_argument("--window", type=int, default=8)
    stability.add_argument("--startup-samples", type=int, default=0)
    stability.add_argument(
        "--comparator",
        choices=["le", "ge"],
        default="le",
        help="le: stable when delta <= tolerance (default), ge: delta >= tolerance",
    )
    stability.add_argument("--json", action="store_true")
    stability.set_defaults(func=_knife_stability)

    plot_criteria = knife_sub.add_parser("plot-criteria", help="Alias of plot criteria")
    plot_criteria.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    plot_criteria.add_argument("--json", action="store_true")
    plot_criteria.set_defaults(func=_plot_metrics)


def _build_plot_parser(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    plot = groups.add_parser(
        "plot",
        help="Log metrics and residual summaries",
        description="Log metrics and residual summaries.",
    )
    plot.set_defaults(func=_help_handler(plot))
    plot_sub = plot.add_subparsers(dest="command", required=False)

    metrics = plot_sub.add_parser("metrics", help="Summarize time/courant/execution metrics")
    metrics.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    metrics.add_argument("--json", action="store_true")
    metrics.set_defaults(func=_plot_metrics)

    criteria = plot_sub.add_parser("criteria", help="Alias of plot metrics")
    criteria.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    criteria.add_argument("--json", action="store_true")
    criteria.set_defaults(func=_plot_metrics)

    residuals = plot_sub.add_parser(
        "residuals",
        help="Summarize residual fields from a solver log",
    )
    residuals.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    residuals.add_argument("--field", action="append", default=[])
    residuals.add_argument("--limit", type=int, default=0)
    residuals.add_argument("--json", action="store_true")
    residuals.set_defaults(func=_plot_residuals)


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
    jobs.add_argument("--json", action="store_true")
    jobs.set_defaults(func=_watch_jobs)

    status = watch_sub.add_parser("status", help="Alias of watch jobs")
    status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    status.add_argument("--all", action="store_true", help="Include finished/stopped jobs")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=_watch_jobs)

    log = watch_sub.add_parser("log", help="Tail a log file (or case solver log)")
    log.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    log.add_argument("--lines", type=int, default=40)
    log.add_argument("--follow", action="store_true")
    log.add_argument("--job-id", default=None, help="Tracked job id from .ofti/jobs.json")
    log.add_argument("--case", dest="case_dir", default=Path.cwd(), type=Path)
    log.add_argument("--json", action="store_true", help="Print result as JSON")
    log.set_defaults(func=_watch_log)

    attach = watch_sub.add_parser("attach", help="Alias of watch log --follow")
    attach.add_argument("source", nargs="?", default=None, type=Path)
    attach.add_argument("--lines", type=int, default=40)
    attach.add_argument("--job-id", default=None, help="Tracked job id from .ofti/jobs.json")
    attach.add_argument("--case", dest="case_dir", default=Path.cwd(), type=Path)
    attach.add_argument("--json", action="store_true", help="Print result as JSON")
    attach.set_defaults(func=_watch_attach)

    start = watch_sub.add_parser("start", help="Start solver in background")
    start.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    start.add_argument("--solver", default=None)
    start.add_argument("--parallel", type=int, default=0)
    start.add_argument("--mpi", default=None)
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
    start.add_argument("--json", action="store_true", help="Print result as JSON")
    start.set_defaults(func=_watch_start)

    pause = watch_sub.add_parser("pause", help="Pause tracked running jobs (SIGSTOP)")
    pause.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    pause.add_argument("--job-id", default=None)
    pause.add_argument("--name", default=None)
    pause.add_argument("--all", action="store_true")
    pause.add_argument("--json", action="store_true")
    pause.set_defaults(func=_watch_pause)

    resume = watch_sub.add_parser("resume", help="Resume paused tracked jobs (SIGCONT)")
    resume.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    resume.add_argument("--job-id", default=None)
    resume.add_argument("--name", default=None)
    resume.add_argument("--all", action="store_true")
    resume.add_argument("--json", action="store_true")
    resume.set_defaults(func=_watch_resume)

    run = watch_sub.add_parser("run", help="Run solver in foreground")
    run.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    run.add_argument("--solver", default=None)
    run.add_argument("--parallel", type=int, default=0)
    run.add_argument("--mpi", default=None)
    run.add_argument("--json", action="store_true", help="Print result as JSON")
    run.set_defaults(func=_watch_run)

    stop = watch_sub.add_parser("stop", help="Stop tracked running jobs")
    stop.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    stop.add_argument("--job-id", default=None)
    stop.add_argument("--name", default=None)
    stop.add_argument("--all", action="store_true")
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
    external.add_argument("--json", action="store_true")
    external.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="External watcher command and arguments (use '--' before command)",
    )
    external.set_defaults(func=_watch_external)


def _build_run_parser(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run = groups.add_parser(
        "run",
        help="Run solver/tools outside the TUI",
        description=(
            "Run solver/tools outside the TUI.\n"
            "Tool names come from built-ins plus case-local presets from ofti.tools."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run.set_defaults(func=_help_handler(run))
    run_sub = run.add_subparsers(dest="command", required=False)

    tool = run_sub.add_parser("tool", help="Run a tool from the OFTI tool catalog")
    tool.add_argument("name", nargs="?")
    tool.add_argument("--case", dest="case_dir", default=Path.cwd(), type=Path)
    tool.add_argument("--list", action="store_true")
    tool.add_argument("--background", action="store_true")
    tool.add_argument("--json", action="store_true", help="Print result as JSON")
    tool.set_defaults(func=_run_tool)

    solver = run_sub.add_parser("solver", help="Run the solver from controlDict application")
    solver.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    solver.add_argument("--solver", default=None)
    solver.add_argument("--parallel", type=int, default=0)
    solver.add_argument("--mpi", default=None, help="MPI launcher (default: mpirun/mpiexec)")
    solver.add_argument("--background", action="store_true")
    solver.add_argument("--dry-run", action="store_true")
    solver.add_argument("--json", action="store_true", help="Print result as JSON")
    solver.set_defaults(func=_run_solver)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 2


def _knife_doctor(args: argparse.Namespace) -> int:
    payload = knife_ops.doctor_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return knife_ops.doctor_exit_code(payload)
    for line in payload["lines"]:
        print(line)
    if payload["errors"]:
        print("\nErrors:")
        for item in payload["errors"]:
            print(f"- {item}")
    if payload["warnings"]:
        print("\nWarnings:")
        for item in payload["warnings"]:
            print(f"- {item}")
    if not payload["errors"] and not payload["warnings"]:
        print("\nOK: no issues found.")
    return knife_ops.doctor_exit_code(payload)


def _knife_preflight(args: argparse.Namespace) -> int:
    payload = knife_ops.preflight_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1
    print(f"case={payload['case']}")
    for key, value in payload["checks"].items():
        print(f"{key}={'ok' if value else 'missing'}")
    if payload["solver_error"]:
        print(f"solver_error={payload['solver_error']}")
    print(f"ok={payload['ok']}")
    return 0 if payload["ok"] else 1


def _knife_compare(args: argparse.Namespace) -> int:
    payload = knife_ops.compare_payload(args.left_case, args.right_case)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"left_case={payload['left_case']}")
    print(f"right_case={payload['right_case']}")
    print(f"diff_count={payload['diff_count']}")
    if not payload["diffs"]:
        print("No dictionary key differences detected.")
        return 0
    for diff in payload["diffs"]:
        print(f"\n{diff['rel_path']}")
        print(f"  kind: {diff.get('kind', 'dict')}")
        if diff["error"]:
            print(f"  error: {diff['error']}")
        missing_left = diff["missing_in_left"]
        missing_right = diff["missing_in_right"]
        if missing_left:
            print(f"  missing_in_left: {', '.join(missing_left)}")
        if missing_right:
            print(f"  missing_in_right: {', '.join(missing_right)}")
        value_diffs = diff.get("value_diffs", [])
        for value in value_diffs[:40]:
            print(f"  value_diff {value['key']}: left={value['left']} right={value['right']}")
        if len(value_diffs) > 40:
            print(f"  value_diff_more={len(value_diffs) - 40}")
        if diff.get("left_hash") or diff.get("right_hash"):
            print(f"  left_hash={diff.get('left_hash')}")
            print(f"  right_hash={diff.get('right_hash')}")
    return 0


def _knife_copy(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.copy_payload(
            args.case_dir,
            args.destination,
            include_runtime_artifacts=bool(args.with_trash),
            drop_mesh=bool(args.drop_mesh),
        )
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"source={payload['source']}")
    print(f"destination={payload['destination']}")
    print(f"include_runtime_artifacts={payload['include_runtime_artifacts']}")
    print(f"drop_mesh={payload['drop_mesh']}")
    print(f"ok={payload['ok']}")
    return 0


def _knife_initials(args: argparse.Namespace) -> int:
    payload = knife_ops.initials_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"initial_dir={payload['initial_dir']}")
    print(f"fields={payload['field_count']} patches={payload['patch_count']}")
    for field in payload["fields"]:
        print(f"\n[{field['name']}]")
        print(f"internalField={field['internal_field'] or '<missing>'}")
        boundary = field.get("boundary", {})
        if not boundary:
            print("boundary=<none>")
            continue
        for patch in sorted(boundary):
            row = boundary[patch]
            print(
                f"- {patch}: type={row.get('type') or 'missing'} "
                f"value={row.get('value') or ''}",
            )
    return 0


def _knife_status(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.status_payload(
            args.case_dir,
            lightweight=bool(getattr(args, "lightweight", False)),
            tail_bytes=getattr(args, "tail_bytes", None),
        )
    except TypeError:
        payload = knife_ops.status_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"latest_time={payload['latest_time']}")
    print(f"latest_iteration={payload.get('latest_iteration')}")
    print(f"latest_deltaT={payload.get('latest_delta_t')}")
    print(f"sec_per_iter={payload.get('sec_per_iter')}")
    if payload["solver_error"]:
        print(f"solver_error={payload['solver_error']}")
    else:
        print(f"solver={payload['solver']}")
        print(f"solver_status={payload['solver_status'] or 'not tracked'}")
    rtc = payload.get("run_time_control", {})
    print(
        "runtime_control="
        f"criteria:{len(rtc.get('criteria', []))} "
        f"pass:{rtc.get('passed', 0)} fail:{rtc.get('failed', 0)} unknown:{rtc.get('unknown', 0)}",
    )
    _print_runtime_criteria(rtc.get("criteria", []))
    print(f"eta_to_criteria_start={payload.get('eta_seconds_to_criteria_start')}")
    print(f"eta_to_end_time={payload.get('eta_seconds_to_end_time')}")
    print(
        f"log_path={payload.get('log_path')} "
        f"fresh={payload.get('log_fresh')} running={payload.get('running')}",
    )
    if payload.get("tracked_solver_processes"):
        print(f"tracked_solver_processes={len(payload['tracked_solver_processes'])}")
    if payload.get("untracked_solver_processes"):
        print(f"untracked_solver_processes={len(payload['untracked_solver_processes'])}")
    print(f"jobs_running={payload['jobs_running']} jobs_total={payload['jobs_total']}")
    return 0


def _knife_current(args: argparse.Namespace) -> int:
    payload = knife_ops.current_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    if payload["solver_error"]:
        print(f"solver_error={payload['solver_error']}")
    else:
        print(f"solver={payload['solver']}")
    if not payload["jobs"]:
        print("No tracked running jobs.")
    else:
        print("tracked_jobs:")
        for job in payload["jobs"]:
            print(
                f"- {job.get('name', 'job')} pid={job.get('pid', '?')} "
                f"status={job.get('status', 'unknown')}",
            )
    if payload["untracked_processes"]:
        print("untracked_solver_processes:")
        for process in payload["untracked_processes"]:
            print(
                f"- pid={process['pid']} solver={process['solver']} "
                f"case={process.get('case')} cmd={process['command']}",
            )
    else:
        print("untracked_solver_processes=none")
    return 0


def _print_runtime_criteria(criteria: list[dict[str, object]]) -> None:
    if not criteria:
        print("criteria=none")
        return
    print("criteria:")
    for row in criteria:
        key = row.get("key")
        status = row.get("status")
        value = row.get("live_value")
        delta = row.get("live_delta")
        tol = row.get("tolerance")
        eta = row.get("eta_seconds")
        reason = row.get("unmet_reason")
        print(
            f"- {key}: status={status} value={value} delta={delta} "
            f"tolerance={tol} eta={eta} unmet_reason={reason}",
        )


def _knife_converge(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.converge_payload(
            args.source,
            strict=bool(args.strict),
            shock_drift_limit=float(args.shock_drift_limit),
            drag_band_limit=float(args.drag_band_limit),
            mass_limit=float(args.mass_limit),
        )
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1
    print(f"log={payload['log']}")
    print(
        f"shock drift={payload['shock']['drift']} limit={payload['shock']['limit']} "
        f"ok={payload['shock']['ok']}",
    )
    print(
        f"drag band={payload['drag']['band']} limit={payload['drag']['limit']} "
        f"ok={payload['drag']['ok']}",
    )
    print(
        "mass "
        f"last_abs_global={payload['mass']['last_abs_global']} limit={payload['mass']['limit']} "
        f"ok={payload['mass']['ok']}",
    )
    print(
        f"residuals flatline={payload['residuals']['flatline']} "
        f"fields={','.join(payload['residuals']['flatline_fields'])}",
    )
    print(
        f"thermo out_of_range_count={payload['thermo']['out_of_range_count']} "
        f"ok={payload['thermo']['ok']}",
    )
    print(f"strict={payload['strict']} strict_ok={payload['strict_ok']}")
    print(f"ok={payload['ok']}")
    return 0 if payload["ok"] else 1


def _knife_stability(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.stability_payload(
            args.source,
            pattern=str(args.pattern),
            tolerance=float(args.tolerance),
            window=int(args.window),
            startup_samples=int(args.startup_samples),
            comparator=str(args.comparator),
        )
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["status"] == "pass" else 1
    print(f"log={payload['log']}")
    print(f"pattern={payload['pattern']}")
    print(
        f"count={payload['count']} window={payload['window']} "
        f"delta={payload['window_delta']} tolerance={payload['tolerance']} "
        f"comparator={payload['comparator']}",
    )
    print(f"latest={payload['latest']}")
    print(f"status={payload['status']} unmet_reason={payload['unmet_reason']}")
    print(f"eta_seconds={payload['eta_seconds']}")
    return 0 if payload["status"] == "pass" else 1


def _knife_set(args: argparse.Namespace) -> int:
    value = " ".join(args.value).strip()
    payload = knife_ops.set_entry_payload(args.case_dir, args.file, args.key, value)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1
    print(f"file={payload['file']}")
    print(f"key={payload['key']}")
    print(f"value={payload['value']}")
    print(f"ok={payload['ok']}")
    return 0 if payload["ok"] else 1


def _plot_metrics(args: argparse.Namespace) -> int:
    try:
        payload = plot_ops.metrics_payload(args.source)
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"log={payload['log']}")
    print(f"time_steps={payload['times']['count']} last={payload['times']['last']}")
    print(f"courant_count={payload['courant']['count']} max={payload['courant']['max']}")
    exec_data = payload["execution_time"]
    print(f"execution_points={exec_data['count']} last={exec_data['last']}")
    if exec_data["delta_avg"] is not None:
        print(
            "step_time="
            f"min:{exec_data['delta_min']} avg:{exec_data['delta_avg']} "
            f"max:{exec_data['delta_max']}",
        )
    print(f"residual_fields={','.join(payload['residual_fields'])}")
    return 0


def _plot_residuals(args: argparse.Namespace) -> int:
    try:
        payload = plot_ops.residuals_payload(
            args.source,
            fields=list(args.field),
            limit=int(args.limit),
        )
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    if not payload["fields"]:
        print(f"No residuals found in {payload['log']}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"log={payload['log']}")
    for row in payload["fields"]:
        print(
            f"{row['field']}: count={row['count']} last={row['last']:.6g} "
            f"min={row['min']:.6g} max={row['max']:.6g}",
        )
    return 0


def _watch_jobs(args: argparse.Namespace) -> int:
    payload = watch_ops.jobs_payload(args.case_dir, include_all=bool(args.all))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    if not payload["jobs"]:
        print("No tracked jobs.")
        return 0
    for job in payload["jobs"]:
        print(
            f"{job.get('name', 'job')} pid={job.get('pid', '?')} "
            f"status={job.get('status', 'unknown')}",
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
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    for line in payload["lines"]:
        print(line)
    if not args.follow:
        return 0

    return _follow_log_path(Path(payload["log"]), interval=0.25)


def _watch_attach(args: argparse.Namespace) -> int:
    attached_args = argparse.Namespace(
        source=args.source if args.source is not None else args.case_dir,
        lines=args.lines,
        follow=True,
        job_id=args.job_id,
        case_dir=args.case_dir,
        json=args.json,
    )
    return _watch_log(attached_args)


def _watch_start(args: argparse.Namespace) -> int:
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


def _watch_external(args: argparse.Namespace) -> int:
    mode = _watch_external_mode(args)
    if mode is None:
        print("ofti: choose only one of --start/--status/--attach/--stop", file=sys.stderr)
        return 2
    command = _watch_external_command(args)
    if mode in {"run", "start"} and not command and not args.dry_run:
        print("ofti: external command is required", file=sys.stderr)
        return 2
    payload = _watch_external_payload(args, mode, command)
    return _watch_external_render(args, mode, payload)


def _watch_external_mode(args: argparse.Namespace) -> str | None:
    enabled = [
        bool(getattr(args, "start", False)),
        bool(getattr(args, "status", False)),
        bool(getattr(args, "attach", False)),
        bool(getattr(args, "stop", False)),
    ]
    if sum(1 for flag in enabled if flag) > 1:
        return None
    if enabled[0]:
        return "start"
    if enabled[1]:
        return "status"
    if enabled[2]:
        return "attach"
    if enabled[3]:
        return "stop"
    return "run"


def _watch_external_command(args: argparse.Namespace) -> list[str]:
    command = list(args.command)
    if command and command[0] == "--":
        return command[1:]
    return command


def _watch_external_payload(
    args: argparse.Namespace,
    mode: str,
    command: list[str],
) -> dict[str, object]:
    if mode == "start":
        return watch_ops.external_watch_start_payload(
            args.case_dir,
            command=command,
            dry_run=bool(args.dry_run),
            name=str(args.name),
            detached=not bool(args.no_detach),
            log_file=args.log_file,
        )
    if mode == "status":
        return watch_ops.external_watch_status_payload(
            args.case_dir,
            job_id=args.job_id,
            name=str(args.name),
            include_all=bool(args.all),
        )
    if mode == "attach":
        return watch_ops.external_watch_attach_payload(
            args.case_dir,
            lines=int(args.lines),
            job_id=args.job_id,
            name=str(args.name),
        )
    if mode == "stop":
        return watch_ops.external_watch_stop_payload(
            args.case_dir,
            job_id=args.job_id,
            name=str(args.name),
            all_jobs=bool(args.all),
            signal_name=str(args.signal),
        )
    return watch_ops.external_watch_payload(
        args.case_dir,
        command=command,
        dry_run=bool(args.dry_run),
    )


def _watch_external_render(
    args: argparse.Namespace,
    mode: str,
    payload: dict[str, object],
) -> int:
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
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
    jobs = cast(list[dict[str, object]], payload.get("jobs", []))
    for job in jobs:
        print(
            f"- id={job.get('id')} name={job.get('name')} pid={job.get('pid')} "
            f"status={job.get('status')}",
        )
    return 0


def _print_watch_external_attach(args: argparse.Namespace, payload: dict[str, object]) -> int:
    lines = cast(list[str], payload.get("lines", []))
    for line in lines:
        print(line)
    if not args.follow:
        return 0
    return _follow_log_path(Path(str(payload["log"])), interval=float(args.interval))


def _print_watch_external_stop(payload: dict[str, object]) -> int:
    print(f"case={payload['case']}")
    print(f"name={payload['name']}")
    print(f"signal={payload['signal']}")
    print(f"selected={payload['selected']}")
    stopped = cast(list[dict[str, object]], payload.get("stopped", []))
    failed = cast(list[dict[str, object]], payload.get("failed", []))
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


def _run_tool(args: argparse.Namespace) -> int:  # noqa: C901, PLR0911
    if args.list:
        payload = run_ops.tool_catalog_payload(args.case_dir)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        for name in payload["tools"]:
            print(name)
        return 0
    if not args.name:
        raise ValueError("tool name is required unless --list is used")
    resolved = run_ops.resolve_tool(args.case_dir, args.name)
    if resolved is None:
        names = run_ops.tool_catalog_names(args.case_dir)
        available = ", ".join(names)
        if args.json:
            print(
                json.dumps(
                    {
                        "error": "unknown tool",
                        "requested": args.name,
                        "available": names,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1
        print(f"Unknown tool: {args.name}", file=sys.stderr)
        if available:
            print(f"Available tools: {available}", file=sys.stderr)
        return 1
    display_name, cmd = resolved
    result = run_ops.execute_case_command(
        args.case_dir,
        display_name,
        cmd,
        background=bool(args.background),
    )
    if args.json:
        payload: dict[str, object] = {
            "case": str(Path(args.case_dir).resolve()),
            "name": display_name,
            "command": run_ops.dry_run_command(cmd),
            "background": bool(args.background),
            "returncode": result.returncode,
            "pid": result.pid,
            "log_path": str(result.log_path) if result.log_path else None,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return result.returncode
    if result.pid is not None:
        print(f"Started {display_name} in background: pid={result.pid} log={result.log_path}")
        return 0
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.returncode


def _run_solver(args: argparse.Namespace) -> int:
    return _run_solver_with_mode(args, background=bool(args.background))


def _run_solver_with_mode(args: argparse.Namespace, *, background: bool) -> int:
    display, cmd = run_ops.solver_command(
        args.case_dir,
        solver=args.solver,
        parallel=int(args.parallel),
        mpi=args.mpi,
    )
    if getattr(args, "dry_run", False):
        cmd_text = run_ops.dry_run_command(cmd)
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "case": str(Path(args.case_dir).resolve()),
                        "name": display,
                        "command": cmd_text,
                        "dry_run": True,
                    },
                    indent=2,
                    sort_keys=True,
                ),
            )
            return 0
        print(cmd_text)
        return 0
    detached = not bool(getattr(args, "no_detach", False))
    log_path_raw = getattr(args, "log_file", None)
    pid_path_raw = getattr(args, "pid_file", None)
    log_path = Path(log_path_raw) if isinstance(log_path_raw, str) and log_path_raw else None
    pid_path = Path(pid_path_raw) if isinstance(pid_path_raw, str) and pid_path_raw else None
    extra_env = _parse_env_assignments(getattr(args, "env", []))
    result = run_ops.execute_case_command(
        args.case_dir,
        display,
        cmd,
        background=background,
        detached=detached,
        log_path=log_path,
        pid_path=pid_path,
        extra_env=extra_env,
    )
    if getattr(args, "json", False):
        payload: dict[str, object] = {
            "case": str(Path(args.case_dir).resolve()),
            "name": display,
            "command": run_ops.dry_run_command(cmd),
            "background": background,
            "detached": detached if background else False,
            "log_file": str(log_path) if log_path is not None else None,
            "pid_file": str(pid_path) if pid_path is not None else None,
            "env": extra_env,
            "returncode": result.returncode,
            "pid": result.pid,
            "log_path": str(result.log_path) if result.log_path else None,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "dry_run": False,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return result.returncode
    if result.pid is not None:
        print(f"Started {display} in background: pid={result.pid} log={result.log_path}")
        return 0
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.returncode


def _parse_env_assignments(raw_values: object) -> dict[str, str]:
    values: list[str] = []
    if isinstance(raw_values, list):
        values = [str(item) for item in raw_values]
    payload: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"invalid --env assignment: {item}")
        key, value = item.split("=", 1)
        name = key.strip()
        if not name:
            raise ValueError(f"invalid --env assignment: {item}")
        payload[name] = value
    return payload
