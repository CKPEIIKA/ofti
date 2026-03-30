from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from textwrap import dedent
from typing import cast

from ofti.core import run_receipt as receipt_ops
from ofti.tools import status_render_service
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import plot as plot_ops
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.cli_tools import watch as watch_ops

Handler = Callable[[argparse.Namespace], int]
_EASY_ON_CPU_TAIL_BYTES = 256 * 1024
_EASY_ON_CPU_MIN_POLL_INTERVAL = 1.0


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
    # Backward-compatible alias.
    parser.add_argument(
        "--lightweight",
        dest="easy_on_cpu",
        action="store_true",
        help=argparse.SUPPRESS,
    )


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
              ofti run parametric CASE --entry application --values simpleFoam,pisoFoam
            """,
        ),
    )
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="Show version and exit",
    )
    parser.set_defaults(func=_help_handler(parser))
    groups = parser.add_subparsers(dest="group", required=False)

    _build_knife_parser(groups)
    _build_plot_parser(groups)
    _build_watch_parser(groups)
    _build_run_parser(groups)
    version_cmd = groups.add_parser("version", help="Show version and exit")
    version_cmd.set_defaults(func=_version_command)
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
    compare.add_argument(
        "--flat",
        action="store_true",
        help="Print flattened key=value style diffs",
    )
    compare.add_argument(
        "--files",
        action="append",
        default=[],
        help="Limit compare to specific relative files (repeatable or comma-separated)",
    )
    compare.add_argument(
        "--raw-hash",
        action="store_true",
        help="Show non-dictionary hash/presence diffs only",
    )
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

    receipt = knife_sub.add_parser(
        "receipt",
        help="Write, verify, and restore immutable run receipts",
    )
    receipt.set_defaults(func=_help_handler(receipt))
    receipt_sub = receipt.add_subparsers(dest="receipt_command", required=False)

    receipt_write = receipt_sub.add_parser("write", help="Write a run receipt for a case")
    receipt_write.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    receipt_write.add_argument("--solver", default=None)
    receipt_write.add_argument("--parallel", type=int, default=0)
    receipt_write.add_argument("--mpi", default=None)
    receipt_write.add_argument(
        "--sync-subdomains",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Recorded launch setting for parallel runs",
    )
    receipt_write.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Recorded launch setting for parallel runs",
    )
    receipt_write.add_argument(
        "--clean-processors",
        action="store_true",
        help="Recorded launch setting for parallel runs",
    )
    receipt_write.add_argument(
        "--receipt-file",
        default=None,
        type=Path,
        help="Receipt JSON path (relative paths resolve from current working directory)",
    )
    receipt_write.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the receipt for restore",
    )
    receipt_write.add_argument("--json", action="store_true")
    receipt_write.set_defaults(func=_knife_receipt_write)

    receipt_verify = receipt_sub.add_parser(
        "verify",
        help="Verify current case inputs against a recorded receipt",
    )
    receipt_verify.add_argument("receipt", type=Path)
    receipt_verify.add_argument("--case", dest="case_dir", default=None, type=Path)
    receipt_verify.add_argument("--json", action="store_true")
    receipt_verify.set_defaults(func=_knife_receipt_verify)

    receipt_restore = receipt_sub.add_parser(
        "restore",
        help="Restore case inputs from a receipt with recorded input copies",
    )
    receipt_restore.add_argument("receipt", type=Path)
    receipt_restore.add_argument("--to", dest="destination", required=True, type=Path)
    receipt_restore.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restore only selected roots: system, constant, 0 (repeatable or comma-separated)",
    )
    receipt_restore.add_argument(
        "--skip",
        action="append",
        default=[],
        help="Skip selected roots: system, constant, 0 (repeatable or comma-separated)",
    )
    receipt_restore.add_argument("--json", action="store_true")
    receipt_restore.set_defaults(func=_knife_receipt_restore)

    initials = knife_sub.add_parser(
        "initials",
        help="Show initial internal fields and boundary conditions",
    )
    initials.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    initials.add_argument("--json", action="store_true")
    initials.set_defaults(func=_knife_initials)

    status = knife_sub.add_parser("status", help="Show solver/job status for a case")
    status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    status_mode = status.add_mutually_exclusive_group()
    status_mode.add_argument(
        "--fast",
        action="store_true",
        help="Use fast tail-only bounded log read (default)",
    )
    status_mode.add_argument(
        "--full",
        action="store_true",
        help="Parse full logs (slower, previous behavior)",
    )
    _add_easy_on_cpu_flag(status)
    status.add_argument(
        "--tail-bytes",
        type=int,
        default=None,
        help="Max log bytes to parse (default: auto when --easy-on-cpu is enabled)",
    )
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=_knife_status)

    current = knife_sub.add_parser("current", help="Show currently tracked running jobs")
    current.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    current.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Scope root directory for campaign view (tracked + untracked across child cases)",
    )
    current.add_argument(
        "--recursive",
        action="store_true",
        help="Enable campaign-wide scan under scope root",
    )
    current.add_argument(
        "--live",
        action="store_true",
        help="Force live /proc scan for untracked solver processes",
    )
    current.add_argument("--json", action="store_true")
    current.set_defaults(func=_knife_current)

    adopt = knife_sub.add_parser(
        "adopt",
        help="Adopt untracked solver processes into OFTI job registry",
    )
    adopt.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    adopt.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Scope root directory for bulk adoption",
    )
    adopt.add_argument(
        "--recursive",
        action="store_true",
        help="Adopt untracked processes for all child cases under case_dir",
    )
    adopt.add_argument(
        "--all-untracked",
        action="store_true",
        help="Alias for bulk recursive adoption under scope root",
    )
    adopt.add_argument("--json", action="store_true")
    adopt.set_defaults(func=_knife_adopt)

    case_status = knife_sub.add_parser("case-status", help="Alias of knife status")
    case_status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    case_status_mode = case_status.add_mutually_exclusive_group()
    case_status_mode.add_argument(
        "--fast",
        action="store_true",
        help="Use fast tail-only bounded log read (default)",
    )
    case_status_mode.add_argument(
        "--full",
        action="store_true",
        help="Parse full logs (slower, previous behavior)",
    )
    _add_easy_on_cpu_flag(case_status)
    case_status.add_argument(
        "--tail-bytes",
        type=int,
        default=None,
        help="Max log bytes to parse (default: auto when --easy-on-cpu is enabled)",
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
    launch.add_argument(
        "--sync-subdomains",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For parallel runs, sync decomposeParDict numberOfSubdomains to --parallel",
    )
    launch.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    launch.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    launch.add_argument(
        "--write-receipt",
        action="store_true",
        help="Write immutable launch receipt under ./runs/",
    )
    launch.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the receipt for restore",
    )
    launch.add_argument(
        "--receipt-file",
        default=None,
        type=Path,
        help="Receipt JSON path (relative paths resolve from current working directory)",
    )
    launch.add_argument("--json", action="store_true", help="Print result as JSON")
    launch.set_defaults(func=_watch_start)

    run = knife_sub.add_parser("run", help="Alias of watch start")
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
    run.set_defaults(func=_watch_start)

    stop = knife_sub.add_parser("stop", help="Stop solver jobs (tracked and untracked)")
    stop.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    stop.add_argument(
        "--case",
        dest="case_override",
        default=None,
        type=Path,
        help="Target case directory (overrides positional case_dir)",
    )
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
    stop.set_defaults(func=_knife_stop)

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

    criteria = knife_sub.add_parser(
        "criteria",
        help="Show runtime criteria as normalized rows",
    )
    criteria.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    criteria_mode = criteria.add_mutually_exclusive_group()
    criteria_mode.add_argument(
        "--fast",
        action="store_true",
        help="Use lightweight log parsing (default)",
    )
    criteria_mode.add_argument("--full", action="store_true", help="Parse full logs (slower)")
    _add_easy_on_cpu_flag(criteria)
    criteria.add_argument("--tail-bytes", type=int, default=None)
    criteria.add_argument("--json", action="store_true")
    criteria.set_defaults(func=_knife_criteria)

    eta = knife_sub.add_parser(
        "eta",
        help="Show ETA by criteria satisfaction or endTime",
    )
    eta.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    eta.add_argument("--mode", choices=["criteria", "endtime"], default="criteria")
    eta_mode = eta.add_mutually_exclusive_group()
    eta_mode.add_argument(
        "--fast",
        action="store_true",
        help="Use lightweight log parsing (default)",
    )
    eta_mode.add_argument("--full", action="store_true", help="Parse full logs (slower)")
    _add_easy_on_cpu_flag(eta)
    eta.add_argument("--tail-bytes", type=int, default=None)
    eta.add_argument("--json", action="store_true")
    eta.set_defaults(func=_knife_eta)

    report = knife_sub.add_parser(
        "report",
        help="Standardized status+criteria+eta report",
    )
    report.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    report.add_argument("--format", choices=["json", "md"], default="json")
    report_mode = report.add_mutually_exclusive_group()
    report_mode.add_argument(
        "--fast",
        action="store_true",
        help="Use lightweight log parsing (default)",
    )
    report_mode.add_argument("--full", action="store_true", help="Parse full logs (slower)")
    _add_easy_on_cpu_flag(report)
    report.add_argument("--tail-bytes", type=int, default=None)
    report.add_argument("--json", action="store_true", help="Alias for --format json")
    report.set_defaults(func=_knife_report)

    campaign = knife_sub.add_parser(
        "campaign",
        help="Manage grouped case sets",
    )
    campaign.set_defaults(func=_help_handler(campaign))
    campaign_sub = campaign.add_subparsers(dest="campaign_command", required=False)

    campaign_list = campaign_sub.add_parser("list", help="List campaign case directories")
    campaign_list.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    campaign_list.add_argument("--glob", default="*")
    campaign_list.add_argument("--summary-csv", default=None, type=Path)
    campaign_list.add_argument("--json", action="store_true")
    campaign_list.set_defaults(func=_knife_campaign_list)

    campaign_status = campaign_sub.add_parser("status", help="Show campaign case status summary")
    campaign_status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    campaign_status.add_argument("--glob", default="*")
    campaign_status.add_argument("--summary-csv", default=None, type=Path)
    campaign_status.add_argument("--tail-bytes", type=int, default=256 * 1024)
    campaign_status.add_argument("--json", action="store_true")
    campaign_status.set_defaults(func=_knife_campaign_status)

    campaign_rank = campaign_sub.add_parser("rank", help="Rank campaign cases")
    campaign_rank.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    campaign_rank.add_argument("--by", choices=["convergence"], default="convergence")
    campaign_rank.add_argument("--glob", default="*")
    campaign_rank.add_argument("--summary-csv", default=None, type=Path)
    campaign_rank.add_argument("--tail-bytes", type=int, default=256 * 1024)
    campaign_rank.add_argument("--json", action="store_true")
    campaign_rank.set_defaults(func=_knife_campaign_rank)

    campaign_stop = campaign_sub.add_parser("stop", help="Stop worst N ranked cases")
    campaign_stop.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    campaign_stop.add_argument("--worst", type=int, required=True)
    campaign_stop.add_argument("--glob", default="*")
    campaign_stop.add_argument("--summary-csv", default=None, type=Path)
    campaign_stop.add_argument(
        "--signal",
        default="TERM",
        choices=["TERM", "INT", "QUIT", "KILL"],
    )
    campaign_stop.add_argument("--dry-run", action="store_true")
    campaign_stop.add_argument("--tail-bytes", type=int, default=256 * 1024)
    campaign_stop.add_argument("--json", action="store_true")
    campaign_stop.set_defaults(func=_knife_campaign_stop)

    campaign_keep = campaign_sub.add_parser("keep", help="Keep best N ranked cases")
    campaign_keep.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    campaign_keep.add_argument("--best", type=int, required=True)
    campaign_keep.add_argument("--glob", default="*")
    campaign_keep.add_argument("--summary-csv", default=None, type=Path)
    campaign_keep.add_argument(
        "--signal",
        default="TERM",
        choices=["TERM", "INT", "QUIT", "KILL"],
    )
    campaign_keep.add_argument("--dry-run", action="store_true")
    campaign_keep.add_argument("--tail-bytes", type=int, default=256 * 1024)
    campaign_keep.add_argument("--json", action="store_true")
    campaign_keep.set_defaults(func=_knife_campaign_keep)

    campaign_compare = campaign_sub.add_parser("compare", help="Compare grouped campaign cases")
    campaign_compare.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    campaign_compare.add_argument("--group-by", choices=["speed"], default="speed")
    campaign_compare.add_argument("--glob", default="*")
    campaign_compare.add_argument("--summary-csv", default=None, type=Path)
    campaign_compare.add_argument("--json", action="store_true")
    campaign_compare.set_defaults(func=_knife_campaign_compare)

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
    jobs.add_argument("--kind", choices=["solver", "watcher", "any"], default="any")
    jobs.add_argument("--output", choices=["brief", "detailed"], default=None)
    jobs.add_argument("--json", action="store_true")
    jobs.set_defaults(func=_watch_jobs)

    status = watch_sub.add_parser("status", help="Alias of watch jobs")
    status.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    status.add_argument("--all", action="store_true", help="Include finished/stopped jobs")
    status.add_argument("--kind", choices=["solver", "watcher", "any"], default="any")
    status.add_argument("--output", choices=["brief", "detailed"], default=None)
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
    solver.add_argument(
        "--sync-subdomains",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For parallel runs, sync decomposeParDict numberOfSubdomains to --parallel",
    )
    solver.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    solver.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    solver.add_argument("--background", action="store_true")
    solver.add_argument("--no-detach", action="store_true")
    solver.add_argument("--log-file", default=None)
    solver.add_argument("--pid-file", default=None)
    solver.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    solver.add_argument(
        "--write-receipt",
        action="store_true",
        help="Write immutable launch receipt under ./runs/",
    )
    solver.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the receipt for restore",
    )
    solver.add_argument(
        "--receipt-file",
        default=None,
        type=Path,
        help="Receipt JSON path (relative paths resolve from current working directory)",
    )
    solver.add_argument("--dry-run", action="store_true")
    solver.add_argument("--json", action="store_true", help="Print result as JSON")
    solver.set_defaults(func=_run_solver)

    matrix = run_sub.add_parser(
        "matrix",
        help="Generate matrix cases from parameter axes and optionally launch them",
    )
    matrix.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    matrix.add_argument(
        "--param",
        action="append",
        default=[],
        help=(
            "Matrix axis: [DICT:]ENTRY=v1,v2. "
            "Examples: application=simpleFoam,pisoFoam "
            "or constant/chemistryProperties:modifiedTemperature=on,off"
        ),
    )
    matrix.add_argument(
        "--dict",
        dest="default_dict",
        default="system/controlDict",
        help="Default dictionary path for --param axes without DICT:",
    )
    matrix.add_argument("--output-root", type=Path, default=None)
    matrix.add_argument("--solver", default=None)
    matrix.add_argument("--parallel", type=int, default=0)
    matrix.add_argument("--mpi", default=None)
    matrix.add_argument("--max-parallel", type=int, default=1)
    matrix.add_argument("--poll-interval", type=float, default=0.25)
    _add_easy_on_cpu_flag(matrix)
    matrix.add_argument(
        "--backend",
        choices=["process", "foamlib-async", "foamlib-slurm"],
        default="process",
        help="Queue backend used when launching generated cases",
    )
    matrix.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    matrix.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    matrix.add_argument("--dry-run", action="store_true")
    matrix.add_argument(
        "--no-launch",
        action="store_true",
        help="Generate cases only (do not launch solver queue)",
    )
    matrix.add_argument("--json", action="store_true", help="Print result as JSON")
    matrix.set_defaults(func=_run_matrix)

    parametric = run_sub.add_parser(
        "parametric",
        help="Generate parametric cases (single/csv/grid) and optionally launch them",
    )
    parametric.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    mode = parametric.add_mutually_exclusive_group()
    mode.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="CSV path for foamlib preprocessing study (relative to case or absolute)",
    )
    mode.add_argument(
        "--grid-axis",
        action="append",
        default=[],
        help="Grid axis: [DICT:]ENTRY=v1,v2 (repeatable)",
    )
    parametric.add_argument(
        "--dict",
        dest="dict_path",
        default="system/controlDict",
        help="Dictionary path for single-entry mode (default: system/controlDict)",
    )
    parametric.add_argument(
        "--entry",
        default=None,
        help="Dictionary entry for single-entry mode, e.g. application",
    )
    parametric.add_argument(
        "--values",
        action="append",
        default=[],
        help="Value list for single-entry mode (comma-separated, repeatable)",
    )
    parametric.add_argument("--output-root", type=Path, default=None)
    parametric.add_argument(
        "--run-solver",
        action="store_true",
        help="Run solver queue for generated cases",
    )
    parametric.add_argument("--solver", default=None)
    parametric.add_argument("--parallel", type=int, default=0)
    parametric.add_argument("--mpi", default=None)
    parametric.add_argument("--max-parallel", type=int, default=1)
    parametric.add_argument("--poll-interval", type=float, default=0.25)
    _add_easy_on_cpu_flag(parametric)
    parametric.add_argument(
        "--backend",
        choices=["process", "foamlib-async", "foamlib-slurm"],
        default="process",
        help="Queue backend used when --run-solver is enabled",
    )
    parametric.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    parametric.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    parametric.add_argument("--json", action="store_true", help="Print result as JSON")
    parametric.set_defaults(func=_run_parametric)

    queue = run_sub.add_parser(
        "queue",
        help="Run a case set in batches with bounded parallelism",
    )
    queue.add_argument("cases", nargs="*", type=Path)
    queue.add_argument("--set", dest="set_dir", default=Path.cwd(), type=Path)
    queue.add_argument("--glob", default="*")
    queue.add_argument("--summary-csv", default=None, type=Path)
    queue.add_argument("--solver", default=None)
    queue.add_argument("--parallel", type=int, default=0)
    queue.add_argument("--mpi", default=None)
    queue.add_argument(
        "--backend",
        choices=["process", "foamlib-async", "foamlib-slurm"],
        default="process",
        help="Queue backend for case launches",
    )
    queue.add_argument("--max-parallel", type=int, required=True)
    queue.add_argument("--poll-interval", type=float, default=0.25)
    _add_easy_on_cpu_flag(queue)
    queue.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    queue.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    queue.add_argument("--dry-run", action="store_true")
    queue.add_argument("--json", action="store_true", help="Print result as JSON")
    queue.set_defaults(func=_run_queue)

    status = run_sub.add_parser(
        "status",
        help="Show compact status table for a case set",
    )
    status.add_argument("cases", nargs="*", type=Path)
    status.add_argument("--set", dest="set_dir", default=Path.cwd(), type=Path)
    status.add_argument("--glob", default="*")
    status.add_argument("--summary-csv", default=None, type=Path)
    status_mode = status.add_mutually_exclusive_group()
    status_mode.add_argument("--fast", action="store_true", help="Use lightweight status parsing")
    status_mode.add_argument("--full", action="store_true", help="Parse full logs (slower)")
    _add_easy_on_cpu_flag(status)
    status.add_argument("--tail-bytes", type=int, default=None)
    status.add_argument("--json", action="store_true", help="Print result as JSON")
    status.set_defaults(func=_run_status)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if bool(getattr(args, "version", False)):
        print(f"ofti {ofti_version()}")
        return 0
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 2


def ofti_version() -> str:
    try:
        return package_version("ofti")
    except PackageNotFoundError:
        return "dev"


def _version_command(_args: argparse.Namespace) -> int:
    print(f"ofti {ofti_version()}")
    return 0


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
    try:
        payload = knife_ops.compare_payload(
            args.left_case,
            args.right_case,
            flat=bool(getattr(args, "flat", False)),
            files=list(getattr(args, "files", [])),
            raw_hash_only=bool(getattr(args, "raw_hash", False)),
        )
    except TypeError:
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
        _print_compare_diff(diff, flat=bool(payload.get("flat")))
    return 0


def _print_compare_diff(diff: dict[str, object], *, flat: bool) -> None:
    print(f"\n{diff['rel_path']}")
    print(f"  kind: {diff.get('kind', 'dict')}")
    if diff["error"]:
        print(f"  error: {diff['error']}")
    missing_left = cast("list[str]", diff.get("missing_in_left", []))
    missing_right = cast("list[str]", diff.get("missing_in_right", []))
    if missing_left:
        print(f"  missing_in_left: {', '.join(missing_left)}")
    if missing_right:
        print(f"  missing_in_right: {', '.join(missing_right)}")
    _print_compare_values(diff, flat=flat)
    if diff.get("left_hash") or diff.get("right_hash"):
        print(f"  left_hash={diff.get('left_hash')}")
        print(f"  right_hash={diff.get('right_hash')}")


def _print_compare_values(diff: dict[str, object], *, flat: bool) -> None:
    if flat:
        values = cast("list[str]", diff.get("value_diffs_flat", []))
        for value in values[:40]:
            print(f"  value_diff {value}")
        if len(values) > 40:
            print(f"  value_diff_more={len(values) - 40}")
        return
    values = cast("list[dict[str, object]]", diff.get("value_diffs", []))
    for value in values[:40]:
        print(
            f"  value_diff {value['key']}: left={value['left']} "
            f"right={value['right']}",
        )
    if len(values) > 40:
        print(f"  value_diff_more={len(values) - 40}")


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


def _knife_receipt_write(args: argparse.Namespace) -> int:
    sync_subdomains = bool(getattr(args, "sync_subdomains", True))
    clean_processors = bool(getattr(args, "clean_processors", False))
    prepare_parallel = bool(getattr(args, "prepare_parallel", True))
    parallel = int(getattr(args, "parallel", 0))
    display, cmd = run_ops.solver_command(
        args.case_dir,
        solver=args.solver,
        parallel=parallel,
        mpi=args.mpi,
        sync_subdomains=sync_subdomains,
    )
    command = run_ops.dry_run_command(cmd)
    receipt_path = receipt_ops.write_case_run_receipt(
        Path(args.case_dir),
        name=display,
        command=command,
        background=False,
        detached=False,
        parallel=parallel,
        mpi=args.mpi,
        sync_subdomains=sync_subdomains,
        prepare_parallel=prepare_parallel,
        clean_processors=clean_processors,
        output=getattr(args, "receipt_file", None),
        record_inputs_copy=bool(getattr(args, "record_inputs_copy", False)),
        solver_name=_solver_name_for_receipt(cmd, parallel=parallel),
    )
    payload = {
        "case": str(Path(args.case_dir).resolve()),
        "command": command,
        "receipt": str(receipt_path),
        "recorded_inputs_copy": bool(getattr(args, "record_inputs_copy", False)),
        "ok": True,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"command={payload['command']}")
    print(f"receipt={payload['receipt']}")
    print(f"recorded_inputs_copy={payload['recorded_inputs_copy']}")
    return 0


def _knife_receipt_verify(args: argparse.Namespace) -> int:
    payload = receipt_ops.verify_run_receipt(
        Path(args.receipt),
        case_path=getattr(args, "case_dir", None),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok")) else 1
    print(f"receipt={payload['receipt']}")
    print(f"case={payload['case']}")
    print(f"ok={payload['ok']}")
    print(f"expected_tree_hash={payload['expected_tree_hash']}")
    print(f"actual_tree_hash={payload['actual_tree_hash']}")
    print(f"openfoam_version_match={payload['openfoam']['match']}")
    print(f"solver_binary_match={payload['build']['solver']['match']}")
    print(f"linked_libs_match={payload['build']['linked_libs']['match']}")
    if payload["missing_files"]:
        print("missing_files:")
        for path in payload["missing_files"]:
            print(f"- {path}")
    if payload["changed_files"]:
        print("changed_files:")
        for row in payload["changed_files"]:
            print(f"- {row['path']}")
    if payload["extra_files"]:
        print("extra_files:")
        for path in payload["extra_files"]:
            print(f"- {path}")
    return 0 if bool(payload.get("ok")) else 1


def _knife_receipt_restore(args: argparse.Namespace) -> int:
    payload = receipt_ops.restore_run_receipt(
        Path(args.receipt),
        Path(args.destination),
        only=getattr(args, "only", []),
        skip=getattr(args, "skip", []),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok")) else 1
    print(f"receipt={payload['receipt']}")
    print(f"destination={payload['destination']}")
    print(f"selected_roots={','.join(payload['selected_roots'])}")
    print(f"restored_receipt={payload['restored_receipt']}")
    if payload["restored"]:
        print("restored:")
        for item in payload["restored"]:
            print(f"- {item}")
    return 0 if bool(payload.get("ok")) else 1


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


def _knife_use_lightweight_mode(args: argparse.Namespace) -> bool:
    return not bool(getattr(args, "full", False))


def _tail_bytes_with_cpu_mode(args: argparse.Namespace) -> int | None:
    explicit = getattr(args, "tail_bytes", None)
    if explicit is not None:
        return int(explicit)
    if bool(getattr(args, "easy_on_cpu", False)):
        return _EASY_ON_CPU_TAIL_BYTES
    return None


def _interval_with_cpu_mode(args: argparse.Namespace, interval: float) -> float:
    value = float(interval)
    if value <= 0:
        value = 0.25
    if bool(getattr(args, "easy_on_cpu", False)):
        value = max(value, _EASY_ON_CPU_MIN_POLL_INTERVAL)
    return value


def _knife_status(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.status_payload(
            args.case_dir,
            lightweight=_knife_use_lightweight_mode(args),
            tail_bytes=_tail_bytes_with_cpu_mode(args),
        )
    except TypeError:
        payload = knife_ops.status_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    for line in status_render_service.case_status_lines(payload):
        print(line)
    return 0


def _knife_current(args: argparse.Namespace) -> int:
    payload = _knife_current_payload(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    _print_knife_current(payload)
    return 0


def _knife_current_payload(args: argparse.Namespace) -> dict[str, object]:
    scope_root = cast("Path", getattr(args, "root", None) or args.case_dir)
    recursive = bool(getattr(args, "recursive", False))
    live = bool(getattr(args, "live", False))
    has_root_override = getattr(args, "root", None) is not None
    scope_is_case = (scope_root / "system" / "controlDict").is_file()
    auto_campaign_scope = live and not scope_is_case and not has_root_override and not recursive
    if recursive or has_root_override or auto_campaign_scope:
        recursive_effective = recursive or auto_campaign_scope
        return _knife_current_scope_payload(
            scope_root,
            live=live,
            recursive=recursive_effective,
        )
    try:
        return knife_ops.current_payload(
            scope_root,
            live=live,
        )
    except TypeError:
        return knife_ops.current_payload(scope_root)


def _print_knife_current(payload: dict[str, object]) -> None:
    print(f"case={payload['case']}")
    if "scope" in payload:
        print(f"scope={payload.get('scope')}")
    if "cases_total" in payload:
        print(f"cases_total={payload.get('cases_total')}")
    if payload["solver_error"]:
        print(f"solver_error={payload['solver_error']}")
    elif payload["solver"]:
        print(f"solver={payload['solver']}")
    else:
        print("solver=<mixed>")
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
                f"role={process.get('role')} case={process.get('case')} "
                f"launcher_pid={process.get('launcher_pid')} cmd={process['command']}",
            )
    else:
        print("untracked_solver_processes=none")


def _knife_current_scope_payload(
    case_dir: Path,
    *,
    live: bool,
    recursive: bool,
) -> dict[str, object]:
    try:
        return knife_ops.current_scope_payload(case_dir, live=live, recursive=recursive)
    except (AttributeError, TypeError):
        try:
            return knife_ops.current_payload(case_dir, live=live)
        except TypeError:
            return knife_ops.current_payload(case_dir)


def _knife_adopt(args: argparse.Namespace) -> int:
    scope_root = cast("Path", getattr(args, "root", None) or args.case_dir)
    payload = _knife_adopt_payload(
        scope_root,
        recursive=bool(getattr(args, "recursive", False)),
        all_untracked=bool(getattr(args, "all_untracked", False)),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not payload["failed"] else 1
    _print_knife_adopt(payload)
    return 0 if not payload["failed"] else 1


def _knife_adopt_payload(
    case_dir: Path,
    *,
    recursive: bool,
    all_untracked: bool,
) -> dict[str, object]:
    try:
        return knife_ops.adopt_payload(
            case_dir,
            recursive=recursive,
            all_untracked=all_untracked,
        )
    except TypeError:
        try:
            return knife_ops.adopt_payload(case_dir, recursive=(recursive or all_untracked))
        except TypeError:
            return knife_ops.adopt_payload(case_dir)


def _print_knife_adopt(payload: dict[str, object]) -> None:
    print(f"case={payload['case']}")
    if "scope" in payload:
        print(f"scope={payload.get('scope')}")
    if "cases_total" in payload:
        print(f"cases_total={payload.get('cases_total')}")
    print(f"selected={payload['selected']}")
    print(f"adopted={len(payload['adopted'])}")
    if payload["adopted"]:
        print("adopted_rows:")
        for row in payload["adopted"]:
            print(
                f"- id={row.get('id')} pid={row.get('pid')} "
                f"role={row.get('role')} name={row.get('name')} case={row.get('case')}",
            )
    if payload["skipped"]:
        print("skipped:")
        for row in payload["skipped"]:
            print(
                f"- pid={row.get('pid')} reason={row.get('reason')} case={row.get('case')}",
            )
    if payload["failed"]:
        print("failed:")
        for row in payload["failed"]:
            print(
                f"- pid={row.get('pid')} error={row.get('error')} case={row.get('case')}",
            )


def _knife_stop(args: argparse.Namespace) -> int:
    case_dir = getattr(args, "case_override", None) or args.case_dir
    payload = knife_ops.stop_payload(
        case_dir,
        job_id=args.job_id,
        name=args.name,
        all_jobs=bool(args.all),
        signal_name=str(getattr(args, "signal", "TERM")),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not payload["failed"] else 1
    print(f"case={payload['case']}")
    print(f"signal={payload.get('signal')}")
    print(f"selected={payload['selected']}")
    if payload["stopped"]:
        print("stopped:")
        for row in payload["stopped"]:
            print(
                f"- pid={row['pid']} kind={row.get('kind', 'solver')} "
                f"name={row.get('name', 'job')}",
            )
    if payload["failed"]:
        print("failed:")
        for row in payload["failed"]:
            print(
                f"- pid={row.get('pid')} kind={row.get('kind', 'solver')} "
                f"error={row['error']}",
            )
    return 0 if not payload["failed"] else 1


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


def _knife_criteria(args: argparse.Namespace) -> int:
    payload = knife_ops.criteria_payload(
        args.case_dir,
        lightweight=_knife_use_lightweight_mode(args),
        tail_bytes=_tail_bytes_with_cpu_mode(args),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not payload.get("failed") else 1
    print(f"case={payload['case']}")
    print(
        f"criteria={payload['criteria_count']} pass={payload['passed']} "
        f"fail={payload['failed']} unknown={payload['unknown']}",
    )
    for row in payload["criteria"]:
        print(
            f"- {row['name']}: met={row['met']} value={row['value']} "
            f"tol={row['tol']} unmet={row['unmet']} source={row['source']}",
        )
    return 0


def _knife_eta(args: argparse.Namespace) -> int:
    payload = knife_ops.eta_payload(
        args.case_dir,
        mode=str(args.mode),
        lightweight=_knife_use_lightweight_mode(args),
        tail_bytes=_tail_bytes_with_cpu_mode(args),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"mode={payload['mode']}")
    print(f"eta_mode={payload.get('eta_mode')}")
    print(f"eta_reason={payload.get('eta_reason')}")
    print(f"eta_confidence={payload.get('eta_confidence')}")
    print(f"eta_seconds={payload['eta_seconds']}")
    print(f"eta_criteria_seconds={payload['eta_criteria_seconds']}")
    print(f"eta_end_time_seconds={payload['eta_end_time_seconds']}")
    return 0


def _knife_report(args: argparse.Namespace) -> int:
    fmt = "json" if bool(getattr(args, "json", False)) else str(getattr(args, "format", "json"))
    payload = knife_ops.report_payload(
        args.case_dir,
        lightweight=_knife_use_lightweight_mode(args),
        tail_bytes=_tail_bytes_with_cpu_mode(args),
    )
    if fmt == "md":
        print(knife_ops.report_markdown(payload))
        return 0
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _knife_campaign_list(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_list_payload(
        args.case_dir,
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"count={payload['count']}")
    for case in payload["cases"]:
        print(f"- {case}")
    return 0


def _knife_campaign_status(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_status_payload(
        args.case_dir,
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        tail_bytes=int(getattr(args, "tail_bytes", 256 * 1024)),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"count={payload['count']}")
    for row in payload["cases"]:
        print(
            f"- {row['case']}: running={row['running']} "
            f"criteria={row['criteria_met']}/{row['criteria_total']} "
            f"worst_ratio={row['criteria_worst_ratio']}",
        )
    return 0


def _knife_campaign_rank(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_rank_payload(
        args.case_dir,
        by=str(getattr(args, "by", "convergence")),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        tail_bytes=int(getattr(args, "tail_bytes", 256 * 1024)),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"count={payload['count']}")
    for idx, row in enumerate(payload["ranked"], start=1):
        print(
            f"{idx}. {row['case']} criteria={row['criteria_met']}/{row['criteria_total']} "
            f"ratio={row['criteria_worst_ratio']}",
        )
    return 0


def _knife_campaign_stop(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_stop_worst_payload(
        args.case_dir,
        worst=int(getattr(args, "worst", 0)),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        signal_name=str(getattr(args, "signal", "TERM")),
        dry_run=bool(getattr(args, "dry_run", False)),
        tail_bytes=int(getattr(args, "tail_bytes", 256 * 1024)),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        failed = [item for item in payload["actions"] if item.get("failed")]
        return 0 if not failed else 1
    print(f"case={payload['case']}")
    print(f"selected={payload['selected']} dry_run={payload['dry_run']}")
    for target in payload["targets"]:
        print(f"- {target}")
    failed = [item for item in payload["actions"] if item.get("failed")]
    return 0 if not failed else 1


def _knife_campaign_keep(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_keep_best_payload(
        args.case_dir,
        best=int(getattr(args, "best", 0)),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        signal_name=str(getattr(args, "signal", "TERM")),
        dry_run=bool(getattr(args, "dry_run", False)),
        tail_bytes=int(getattr(args, "tail_bytes", 256 * 1024)),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        failed = [item for item in payload["actions"] if item.get("failed")]
        return 0 if not failed else 1
    print(f"case={payload['case']}")
    print(f"kept={payload['kept']} stopped={payload['stopped']} dry_run={payload['dry_run']}")
    for target in payload["targets"]:
        print(f"- {target}")
    failed = [item for item in payload["actions"] if item.get("failed")]
    return 0 if not failed else 1


def _knife_campaign_compare(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_compare_payload(
        args.case_dir,
        group_by=str(getattr(args, "group_by", "speed")),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"case={payload['case']}")
    print(f"group_by={payload['group_by']} groups={payload['group_count']}")
    for key, values in payload["groups"].items():
        print(f"- {key}: {len(values)} case(s)")
    print(f"comparisons={len(payload['comparisons'])}")
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
    interval = _interval_with_cpu_mode(args, base_interval)
    return _follow_log_path(Path(payload["log"]), interval=interval)


def _watch_attach(args: argparse.Namespace) -> int:
    watcher_raw = getattr(args, "watcher", None)
    if watcher_raw is not None:
        if getattr(args, "adopt", None):
            print("ofti: --adopt cannot be used with --watcher", file=sys.stderr)
            return 2
        try:
            extra_env = _parse_env_assignments(getattr(args, "env", []))
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
            extra_env = _parse_env_assignments(getattr(args, "env", []))
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
    if "count" in payload:
        base["count"] = payload.get("count")
    if "jobs" in payload:
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
    if "log" in payload:
        lines = cast("list[str]", payload.get("lines", []))
        base["log"] = payload.get("log")
        base["line_count"] = len(lines)
        base["lines"] = lines
    if "selected" in payload:
        base["selected"] = payload.get("selected")
    if "signal" in payload:
        base["signal"] = payload.get("signal")
    if "pid" in payload:
        base["pid"] = payload.get("pid")
    if "job_id" in payload:
        base["job_id"] = payload.get("job_id")
    if "kind" in payload:
        base["kind"] = payload.get("kind")
    if "detached" in payload:
        base["detached"] = payload.get("detached")
    if "running" in payload:
        base["running"] = payload.get("running")
    if "log_path" in payload:
        base["log_path"] = payload.get("log_path")
    return base


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


def _run_matrix(args: argparse.Namespace) -> int:
    axes = run_ops.parse_matrix_axes(
        list(getattr(args, "param", [])),
        default_dict=str(getattr(args, "default_dict", "system/controlDict")),
    )
    generated = run_ops.matrix_case_payload(
        args.case_dir,
        axes=axes,
        output_root=getattr(args, "output_root", None),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    launch = not bool(getattr(args, "no_launch", False))
    queue_result: dict[str, object] | None = None
    if launch:
        case_paths = [Path(str(row["case"])) for row in generated["cases"]]
        poll_interval = _interval_with_cpu_mode(args, float(getattr(args, "poll_interval", 0.25)))
        queue_result = run_ops.queue_payload(
            cases=case_paths,
            solver=getattr(args, "solver", None),
            parallel=int(getattr(args, "parallel", 0)),
            mpi=getattr(args, "mpi", None),
            max_parallel=int(getattr(args, "max_parallel", 1)),
            poll_interval=poll_interval,
            dry_run=bool(getattr(args, "dry_run", False)),
            backend=str(getattr(args, "backend", "process")),
            prepare_parallel=bool(getattr(args, "prepare_parallel", True)),
            clean_processors=bool(getattr(args, "clean_processors", False)),
        )
    payload: dict[str, object] = {
        **generated,
        "launch": launch,
        "queue": queue_result,
    }
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        if queue_result and queue_result.get("ok") is False:
            return 1
        return 0
    print(f"template_case={payload['template_case']}")
    print(
        f"case_count={payload['case_count']} launch={payload['launch']} "
        f"dry_run={payload['dry_run']}",
    )
    for row in generated["cases"]:
        print(f"- {row['case']}")
    if queue_result:
        print(
            f"queue max_parallel={queue_result['max_parallel']} "
            f"backend={queue_result.get('backend', 'process')} "
            f"started={len(queue_result['started'])} "
            f"failed_to_start={len(queue_result['failed_to_start'])}",
        )
        if queue_result["failed_to_start"]:
            for row in queue_result["failed_to_start"]:
                print(f"  failed {row['case']}: {row['error']}")
    if queue_result and queue_result.get("ok") is False:
        return 1
    return 0


def _run_parametric(args: argparse.Namespace) -> int:
    poll_interval = _interval_with_cpu_mode(args, float(getattr(args, "poll_interval", 0.25)))
    values = run_ops.parse_sweep_values(list(getattr(args, "values", [])))
    grid_axes = run_ops.parse_grid_axes(
        list(getattr(args, "grid_axis", [])),
        default_dict=str(getattr(args, "dict_path", "system/controlDict")),
    )
    payload = run_ops.parametric_case_payload(
        args.case_dir,
        dict_path=str(getattr(args, "dict_path", "system/controlDict")),
        entry=getattr(args, "entry", None),
        values=values,
        csv_path=getattr(args, "csv", None),
        grid_axes=grid_axes,
        output_root=getattr(args, "output_root", None),
        run_solver=bool(getattr(args, "run_solver", False)),
        solver=getattr(args, "solver", None),
        parallel=int(getattr(args, "parallel", 0)),
        mpi=getattr(args, "mpi", None),
        max_parallel=int(getattr(args, "max_parallel", 1)),
        poll_interval=poll_interval,
        queue_backend=str(getattr(args, "backend", "process")),
        prepare_parallel=bool(getattr(args, "prepare_parallel", True)),
        clean_processors=bool(getattr(args, "clean_processors", False)),
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        queue = cast("dict[str, object] | None", payload.get("queue"))
        if queue and queue.get("ok") is False:
            return 1
        return 0
    print(f"case={payload['case']}")
    print(
        f"mode={payload['mode']} created={payload['created_count']} "
        f"run_solver={payload['run_solver']}",
    )
    for path in cast("list[str]", payload["created"]):
        print(f"- {path}")
    queue = cast("dict[str, object] | None", payload.get("queue"))
    if queue:
        print(
            f"queue max_parallel={queue['max_parallel']} "
            f"backend={queue.get('backend', 'process')} "
            f"started={len(cast('list[object]', queue['started']))} "
            f"failed_to_start={len(cast('list[object]', queue['failed_to_start']))}",
        )
        if queue.get("ok") is False:
            return 1
    return 0


def _run_queue(args: argparse.Namespace) -> int:
    poll_interval = _interval_with_cpu_mode(args, float(getattr(args, "poll_interval", 0.25)))
    cases = run_ops.resolve_case_set(
        set_dir=args.set_dir,
        explicit_cases=list(getattr(args, "cases", [])),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
    )
    payload = run_ops.queue_payload(
        cases=cases,
        solver=getattr(args, "solver", None),
        parallel=int(getattr(args, "parallel", 0)),
        mpi=getattr(args, "mpi", None),
        max_parallel=int(getattr(args, "max_parallel", 1)),
        poll_interval=poll_interval,
        dry_run=bool(getattr(args, "dry_run", False)),
        backend=str(getattr(args, "backend", "process")),
        prepare_parallel=bool(getattr(args, "prepare_parallel", True)),
        clean_processors=bool(getattr(args, "clean_processors", False)),
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok", True)) else 1
    print(
        f"count={payload['count']} max_parallel={payload['max_parallel']} "
        f"backend={payload.get('backend', 'process')} dry_run={payload['dry_run']}",
    )
    print(
        f"started={len(payload['started'])} finished={len(payload['finished'])} "
        f"failed_to_start={len(payload['failed_to_start'])}",
    )
    for row in payload["finished"]:
        print(f"- {row['case']}: state={row['state']} latest_time={row['latest_time']}")
    if payload["failed_to_start"]:
        for row in payload["failed_to_start"]:
            print(f"failed {row['case']}: {row['error']}")
    return 0 if bool(payload.get("ok", True)) else 1


def _run_status(args: argparse.Namespace) -> int:
    payload = run_ops.status_set_payload(
        set_dir=args.set_dir,
        explicit_cases=list(getattr(args, "cases", [])),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        lightweight=not bool(getattr(args, "full", False)),
        tail_bytes=_tail_bytes_with_cpu_mode(args),
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"set={payload['set_dir']} count={payload['count']}")
    print("STATE   LATEST_TIME   ETA(s)    STOP_REASON   CASE")
    for row in payload["rows"]:
        state = str(row.get("state", "unknown"))
        latest = row.get("latest_time")
        eta = row.get("eta_seconds")
        reason = str(row.get("stop_reason") or "-")
        case = str(row.get("case"))
        latest_text = f"{latest}" if latest is not None else "-"
        eta_text = f"{eta:.2f}" if isinstance(eta, (int, float)) else "-"
        print(f"{state:<7} {latest_text:<12} {eta_text:<8} {reason:<12} {case}")
    return 0


def _run_tool(args: argparse.Namespace) -> int:
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
    sync_subdomains = bool(getattr(args, "sync_subdomains", True))
    clean_processors = bool(getattr(args, "clean_processors", False))
    prepare_parallel = bool(getattr(args, "prepare_parallel", True))
    parallel = int(getattr(args, "parallel", 0))
    display, cmd = run_ops.solver_command(
        args.case_dir,
        solver=args.solver,
        parallel=parallel,
        mpi=args.mpi,
        sync_subdomains=sync_subdomains,
    )
    if getattr(args, "dry_run", False):
        return _run_solver_dry_run(
            args,
            display=display,
            cmd=cmd,
            parallel=parallel,
            sync_subdomains=sync_subdomains,
            clean_processors=clean_processors,
            prepare_parallel=prepare_parallel,
        )
    return _run_solver_execute(
        args,
        background=background,
        display=display,
        cmd=cmd,
        parallel=parallel,
        sync_subdomains=sync_subdomains,
        clean_processors=clean_processors,
        prepare_parallel=prepare_parallel,
    )


def _run_solver_dry_run(
    args: argparse.Namespace,
    *,
    display: str,
    cmd: list[str],
    parallel: int,
    sync_subdomains: bool,
    clean_processors: bool,
    prepare_parallel: bool,
) -> int:
    parallel_setup = _parallel_setup_payload(
        args.case_dir,
        cmd=cmd,
        parallel=parallel,
        clean_processors=clean_processors,
        prepare_parallel=prepare_parallel,
        dry_run=True,
        extra_env=None,
    )
    cmd_text = run_ops.dry_run_command(cmd)
    write_receipt = _write_receipt_enabled(args)
    receipt_path = (
        _planned_receipt_path(args.case_dir, getattr(args, "receipt_file", None))
        if write_receipt
        else None
    )
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "case": str(Path(args.case_dir).resolve()),
                    "name": display,
                    "command": cmd_text,
                    "dry_run": True,
                    "sync_subdomains": sync_subdomains,
                    "clean_processors": clean_processors,
                    "prepare_parallel": prepare_parallel,
                    "write_receipt": write_receipt,
                    "record_inputs_copy": bool(getattr(args, "record_inputs_copy", False)),
                    "receipt_path": str(receipt_path) if receipt_path is not None else None,
                    "parallel_setup": parallel_setup,
                },
                indent=2,
                sort_keys=True,
            ),
        )
        return 0
    print(cmd_text)
    if parallel_setup is not None:
        print(
            f"# pre: decompose={parallel_setup.get('decompose_command')} "
            f"clean_processors={clean_processors}",
        )
    elif parallel > 1 and "-parallel" in cmd:
        print("# pre: skipped (--no-prepare-parallel)")
    if receipt_path is not None:
        print(f"# receipt: {receipt_path}")
    return 0


def _run_solver_execute(
    args: argparse.Namespace,
    *,
    background: bool,
    display: str,
    cmd: list[str],
    parallel: int,
    sync_subdomains: bool,
    clean_processors: bool,
    prepare_parallel: bool,
) -> int:
    detached = not bool(getattr(args, "no_detach", False))
    log_path_raw = getattr(args, "log_file", None)
    pid_path_raw = getattr(args, "pid_file", None)
    log_path = Path(log_path_raw) if isinstance(log_path_raw, str) and log_path_raw else None
    pid_path = Path(pid_path_raw) if isinstance(pid_path_raw, str) and pid_path_raw else None
    extra_env = _parse_env_assignments(getattr(args, "env", []))
    write_receipt = _write_receipt_enabled(args)
    receipt_output = (
        _planned_receipt_path(args.case_dir, getattr(args, "receipt_file", None))
        if write_receipt
        else None
    )
    parallel_setup = _parallel_setup_payload(
        args.case_dir,
        cmd=cmd,
        parallel=parallel,
        clean_processors=clean_processors,
        prepare_parallel=prepare_parallel,
        dry_run=False,
        extra_env=extra_env,
    )
    result = run_ops.execute_solver_case_command(
        args.case_dir,
        display,
        cmd,
        parallel=parallel,
        mpi=args.mpi,
        background=background,
        detached=detached,
        log_path=log_path,
        pid_path=pid_path,
        extra_env=extra_env,
    )
    written_receipt: Path | None = None
    if write_receipt:
        written_receipt = receipt_ops.write_case_run_receipt(
            Path(args.case_dir),
            name=display,
            command=run_ops.dry_run_command(cmd),
            background=background,
            detached=detached if background else False,
            parallel=parallel,
            mpi=args.mpi,
            sync_subdomains=sync_subdomains,
            prepare_parallel=prepare_parallel,
            clean_processors=clean_processors,
            extra_env=extra_env,
            log_path=result.log_path,
            pid=result.pid,
            returncode=result.returncode,
            output=receipt_output,
            record_inputs_copy=bool(getattr(args, "record_inputs_copy", False)),
            solver_name=_solver_name_for_receipt(cmd, parallel=parallel),
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
            "sync_subdomains": sync_subdomains,
            "clean_processors": clean_processors,
            "prepare_parallel": prepare_parallel,
            "write_receipt": write_receipt,
            "record_inputs_copy": bool(getattr(args, "record_inputs_copy", False)),
            "receipt_path": str(written_receipt) if written_receipt is not None else None,
            "parallel_setup": parallel_setup,
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
        if written_receipt is not None:
            print(f"Receipt: {written_receipt}")
        return 0
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if written_receipt is not None:
        print(f"Receipt: {written_receipt}")
    return result.returncode


def _parallel_setup_payload(
    case_dir: Path,
    *,
    cmd: list[str],
    parallel: int,
    clean_processors: bool,
    prepare_parallel: bool,
    dry_run: bool,
    extra_env: dict[str, str] | None,
) -> dict[str, object] | None:
    if not (parallel > 1 and "-parallel" in cmd and prepare_parallel):
        return None
    return cast(
        "dict[str, object]",
        run_ops.prepare_parallel_case(
            case_dir,
            parallel=parallel,
            clean_processors=clean_processors,
            extra_env=extra_env,
            dry_run=dry_run,
        ),
    )


def _write_receipt_enabled(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "write_receipt", False)
        or getattr(args, "record_inputs_copy", False)
        or getattr(args, "receipt_file", None) is not None,
    )


def _planned_receipt_path(case_dir: Path, receipt_file: object) -> Path:
    output = receipt_file if isinstance(receipt_file, Path) else None
    return receipt_ops.resolve_receipt_output(Path(case_dir), output)


def _solver_name_for_receipt(cmd: list[str], *, parallel: int) -> str | None:
    solver = run_ops._solver_token_from_command(cmd, parallel=parallel)
    return str(solver) if solver else None


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
