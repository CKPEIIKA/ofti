from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from textwrap import dedent

from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import plot as plot_ops
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.cli_tools import watch as watch_ops


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
    groups = parser.add_subparsers(dest="group", required=True)

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
    knife_sub = knife.add_subparsers(dest="command", required=True)

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

    status = knife_sub.add_parser("status", help="Show solver/job status for a case")
    status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=_knife_status)

    current = knife_sub.add_parser("current", help="Show currently tracked running jobs")
    current.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    current.add_argument("--json", action="store_true")
    current.set_defaults(func=_knife_current)

    case_status = knife_sub.add_parser("case-status", help="Alias of knife status")
    case_status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
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
    stop.add_argument("--json", action="store_true")
    stop.set_defaults(func=_watch_stop)

    converge = knife_sub.add_parser("converge", help="Alias of plot residuals")
    converge.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    converge.add_argument("--field", action="append", default=[])
    converge.add_argument("--limit", type=int, default=0)
    converge.add_argument("--json", action="store_true")
    converge.set_defaults(func=_plot_residuals)

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
    plot_sub = plot.add_subparsers(dest="command", required=True)

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
    watch_sub = watch.add_subparsers(dest="command", required=True)

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
    start.add_argument("--json", action="store_true", help="Print result as JSON")
    start.set_defaults(func=_watch_start)

    resume = watch_sub.add_parser("resume", help="Resume solver in background")
    resume.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    resume.add_argument("--solver", default=None)
    resume.add_argument("--parallel", type=int, default=0)
    resume.add_argument("--mpi", default=None)
    resume.add_argument("--json", action="store_true", help="Print result as JSON")
    resume.set_defaults(func=_watch_start)

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
    stop.add_argument("--json", action="store_true")
    stop.set_defaults(func=_watch_stop)


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
    run_sub = run.add_subparsers(dest="command", required=True)

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
        if diff["error"]:
            print(f"  error: {diff['error']}")
            continue
        missing_left = diff["missing_in_left"]
        missing_right = diff["missing_in_right"]
        if missing_left:
            print(f"  missing_in_left: {', '.join(missing_left)}")
        if missing_right:
            print(f"  missing_in_right: {', '.join(missing_right)}")
    return 0


def _knife_status(args: argparse.Namespace) -> int:
    payload = knife_ops.status_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"latest_time={payload['latest_time']}")
    if payload["solver_error"]:
        print(f"solver_error={payload['solver_error']}")
    else:
        print(f"solver={payload['solver']}")
        print(f"solver_status={payload['solver_status'] or 'not tracked'}")
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
                f"cmd={process['command']}",
            )
    else:
        print("untracked_solver_processes=none")
    return 0


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


def _watch_log(args: argparse.Namespace) -> int:  # noqa: C901
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

    log_path = Path(payload["log"])
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(0, 2)
            while True:
                line = handle.readline()
                if line:
                    print(line.rstrip("\n"), flush=True)
                    continue
                time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"Failed to follow {log_path}: {exc}", file=sys.stderr)
        return 1


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
    payload = watch_ops.stop_payload(
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
    if payload["stopped"]:
        print("stopped:")
        for row in payload["stopped"]:
            print(f"- id={row['id']} pid={row['pid']} name={row['name']}")
    if payload["failed"]:
        print("failed:")
        for row in payload["failed"]:
            print(f"- id={row.get('id')} pid={row.get('pid')} error={row['error']}")
    return 0 if not payload["failed"] else 1


def _run_tool(args: argparse.Namespace) -> int:  # noqa: C901, PLR0911
    if args.list:
        names = run_ops.tool_catalog_names(args.case_dir)
        if args.json:
            print(
                json.dumps(
                    {"case": str(Path(args.case_dir).resolve()), "tools": names},
                    indent=2,
                    sort_keys=True,
                ),
            )
            return 0
        for name in names:
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
    result = run_ops.execute_case_command(
        args.case_dir,
        display,
        cmd,
        background=background,
    )
    if getattr(args, "json", False):
        payload: dict[str, object] = {
            "case": str(Path(args.case_dir).resolve()),
            "name": display,
            "command": run_ops.dry_run_command(cmd),
            "background": background,
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
