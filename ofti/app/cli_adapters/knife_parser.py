"""argparse builder for the `ofti knife` command group.

Split out of cli_adapters/knife.py (which now holds the handlers). This module
imports the handler functions and wires them to subparsers via set_defaults.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ofti.app.cli_adapters.command_builder import build_spec_parser
from ofti.app.cli_adapters.knife import (
    _knife_adopt,
    _knife_campaign_compare,
    _knife_campaign_keep,
    _knife_campaign_list,
    _knife_campaign_rank,
    _knife_campaign_status,
    _knife_campaign_stop,
    _knife_compare,
    _knife_compare_fields,
    _knife_converge,
    _knife_copy,
    _knife_criteria,
    _knife_current,
    _knife_doctor,
    _knife_eta,
    _knife_initials,
    _knife_manifest_restore,
    _knife_manifest_verify,
    _knife_manifest_write,
    _knife_physical,
    _knife_preflight,
    _knife_report,
    _knife_set,
    _knife_stability,
    _knife_status,
    _knife_stop,
)
from ofti.app.cli_adapters.plot import _plot_metrics
from ofti.app.cli_adapters.watch import _watch_pause, _watch_resume, _watch_start
from ofti.app.cli_help import _add_easy_on_cpu_flag, _add_table_flag, _help_handler
from ofti.plugins import discover_plugins


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
    _add_table_flag(doctor)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=_knife_doctor)

    preflight = knife_sub.add_parser("preflight", help="Check basic case/run prerequisites")
    preflight.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(preflight)
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
    _add_table_flag(compare)
    compare.add_argument("--json", action="store_true")
    compare.set_defaults(func=_knife_compare)

    physical = knife_sub.add_parser(
        "physical",
        help="Scan field values for finite and physically plausible values",
    )
    physical.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    physical.add_argument(
        "--time",
        default="latest",
        help="Time directory to scan (default: latest)",
    )
    physical.add_argument(
        "--fields",
        action="append",
        default=[],
        help="Comma-separated field names to scan; repeatable",
    )
    physical.add_argument(
        "--field",
        dest="field_rules",
        action="append",
        default=[],
        help="Custom check rule like rho:min=0 (finite by default; nofinite to skip); repeatable",
    )
    physical.add_argument("--patch", default=None, help="Check a boundary patch value")
    physical.add_argument(
        "--out",
        default=None,
        type=Path,
        help="Write physical.csv and physical.md",
    )
    physical.add_argument(
        "--profile",
        default=None,
        help="Physical rule profile from installed plugins, e.g. simplefoam",
    )
    physical.add_argument(
        "--fail-on-bad",
        action="store_true",
        help="Exit nonzero on physical violations",
    )
    physical.add_argument("--json", action="store_true")
    physical.set_defaults(func=_knife_physical)

    compare_fields = knife_sub.add_parser(
        "compare-fields",
        help="Compare numeric internal field values between two cases",
    )
    compare_fields.add_argument("left_case", nargs="?", type=Path)
    compare_fields.add_argument("right_case", nargs="?", type=Path)
    compare_fields.add_argument("--reference", default=None, type=Path)
    compare_fields.add_argument("--candidate", default=None, type=Path)
    compare_fields.add_argument(
        "--time",
        default="latest",
        help="Time directory to compare (default: latest)",
    )
    compare_fields.add_argument("--reference-time", default=None)
    compare_fields.add_argument("--candidate-time", default=None)
    compare_fields.add_argument(
        "--fields",
        action="append",
        default=[],
        help="Comma-separated field names to compare; repeatable",
    )
    compare_fields.add_argument(
        "--preset",
        default=None,
        help="Field preset name (built-in: flow; plugins may add more)",
    )
    compare_fields.add_argument("--patch", default=None, help="Compare boundary patch value")
    compare_fields.add_argument(
        "--out",
        default=None,
        type=Path,
        help="Write latest.csv and latest.md",
    )
    compare_fields.add_argument("--abs-tol", type=float, default=1e-300)
    compare_fields.add_argument("--rel-tol", type=float, default=1e-12)
    compare_fields.add_argument("--json", action="store_true")
    compare_fields.set_defaults(func=_knife_compare_fields)

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

    manifest = knife_sub.add_parser(
        "manifest",
        help="Write, verify, and restore immutable run manifests",
    )
    manifest.set_defaults(func=_help_handler(manifest))
    manifest_sub = manifest.add_subparsers(dest="manifest_command", required=False)

    manifest_write = manifest_sub.add_parser("write", help="Write a run manifest for a case")
    manifest_write.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    manifest_write.add_argument("--solver", default=None)
    manifest_write.add_argument("--parallel", type=int, default=0)
    manifest_write.add_argument("--mpi", default=None)
    manifest_write.add_argument(
        "--sync-subdomains",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Recorded launch setting for parallel runs",
    )
    manifest_write.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Recorded launch setting for parallel runs",
    )
    manifest_write.add_argument(
        "--clean-processors",
        action="store_true",
        help="Recorded launch setting for parallel runs",
    )
    manifest_write.add_argument(
        "--manifest-file",
        "--receipt-file",
        dest="manifest_file",
        default=None,
        type=Path,
        help="Manifest JSON path (relative paths resolve from current working directory)",
    )
    manifest_write.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the manifest for restore",
    )
    manifest_write.add_argument("--json", action="store_true")
    manifest_write.set_defaults(func=_knife_manifest_write)

    manifest_verify = manifest_sub.add_parser(
        "verify",
        help="Verify current case inputs against a recorded manifest",
    )
    manifest_verify.add_argument(
        "manifest",
        type=Path,
        help="Manifest file, or a directory containing runs/*/manifest.json",
    )
    manifest_verify.add_argument("--case", dest="case_dir", default=None, type=Path)
    manifest_verify.add_argument("--json", action="store_true")
    manifest_verify.set_defaults(func=_knife_manifest_verify)

    manifest_restore = manifest_sub.add_parser(
        "restore",
        help="Restore case inputs from a manifest with recorded input copies",
    )
    manifest_restore.add_argument(
        "manifest",
        type=Path,
        help="Manifest file, or a directory containing runs/*/manifest.json",
    )
    manifest_restore.add_argument("--to", dest="destination", required=True, type=Path)
    manifest_restore.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restore only selected roots: system, constant, 0 (repeatable or comma-separated)",
    )
    manifest_restore.add_argument(
        "--skip",
        action="append",
        default=[],
        help="Skip selected roots: system, constant, 0 (repeatable or comma-separated)",
    )
    manifest_restore.add_argument("--json", action="store_true")
    manifest_restore.set_defaults(func=_knife_manifest_restore)

    initials = knife_sub.add_parser(
        "initials",
        help="Show initial internal fields and boundary conditions",
    )
    initials.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(initials)
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
    _add_table_flag(status)
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
    _add_table_flag(current)
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
    _add_table_flag(case_status)
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
        "--write-manifest",
        "--write-receipt",
        dest="write_manifest",
        action="store_true",
        help="Write immutable launch manifest under ./runs/",
    )
    launch.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the manifest for restore",
    )
    launch.add_argument(
        "--manifest-file",
        "--receipt-file",
        dest="manifest_file",
        default=None,
        type=Path,
        help="Manifest JSON path (relative paths resolve from current working directory)",
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
        "--write-manifest",
        "--write-receipt",
        dest="write_manifest",
        action="store_true",
        help="Write immutable launch manifest under ./runs/",
    )
    run.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the manifest for restore",
    )
    run.add_argument(
        "--manifest-file",
        "--receipt-file",
        dest="manifest_file",
        default=None,
        type=Path,
        help="Manifest JSON path (relative paths resolve from current working directory)",
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
    _add_table_flag(converge)
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
    _add_table_flag(stability)
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
    _add_table_flag(criteria)
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
    _add_table_flag(eta)
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
    _add_table_flag(report)
    report.add_argument("--json", action="store_true", help="Alias for --format json")
    report.set_defaults(func=_knife_report)

    campaign = knife_sub.add_parser(
        "campaign",
        help="Manage grouped case sets",
    )
    campaign.set_defaults(func=_help_handler(campaign))
    campaign_sub = campaign.add_subparsers(dest="campaign_command", required=False)

    campaign_list = campaign_sub.add_parser(
        "list",
        help="List campaign case directories",
        description="List OpenFOAM cases under a campaign/root directory.",
    )
    campaign_list.add_argument(
        "case_dir",
        nargs="?",
        default=Path.cwd(),
        type=Path,
        help="Campaign root or case directory (default: current directory)",
    )
    campaign_list.add_argument("--glob", default="*", help="Case directory glob under case_dir")
    campaign_list.add_argument(
        "--summary-csv",
        default=None,
        type=Path,
        help="Read case paths from a campaign summary CSV",
    )
    _add_table_flag(campaign_list)
    campaign_list.add_argument("--json", action="store_true", help="Print result as JSON")
    campaign_list.set_defaults(func=_knife_campaign_list)

    campaign_status = campaign_sub.add_parser(
        "status",
        help="Show campaign case status summary",
        description="Summarize status/runtime criteria for cases in a campaign.",
    )
    campaign_status.add_argument(
        "case_dir",
        nargs="?",
        default=Path.cwd(),
        type=Path,
        help="Campaign root or case directory (default: current directory)",
    )
    campaign_status.add_argument("--glob", default="*", help="Case directory glob under case_dir")
    campaign_status.add_argument(
        "--summary-csv",
        default=None,
        type=Path,
        help="Read case paths from a campaign summary CSV",
    )
    campaign_status.add_argument(
        "--tail-bytes",
        type=int,
        default=256 * 1024,
        help="Max solver log bytes to parse per case",
    )
    _add_table_flag(campaign_status)
    campaign_status.add_argument("--json", action="store_true", help="Print result as JSON")
    campaign_status.set_defaults(func=_knife_campaign_status)

    campaign_rank = campaign_sub.add_parser(
        "rank",
        help="Rank campaign cases",
        description="Rank campaign cases by read-only convergence/status metrics.",
    )
    campaign_rank.add_argument(
        "case_dir",
        nargs="?",
        default=Path.cwd(),
        type=Path,
        help="Campaign root or case directory (default: current directory)",
    )
    campaign_rank.add_argument("--by", choices=["convergence"], default="convergence")
    campaign_rank.add_argument("--glob", default="*", help="Case directory glob under case_dir")
    campaign_rank.add_argument(
        "--summary-csv",
        default=None,
        type=Path,
        help="Read case paths from a campaign summary CSV",
    )
    campaign_rank.add_argument(
        "--tail-bytes",
        type=int,
        default=256 * 1024,
        help="Max solver log bytes to parse per case",
    )
    _add_table_flag(campaign_rank)
    campaign_rank.add_argument("--json", action="store_true", help="Print result as JSON")
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

    campaign_compare = campaign_sub.add_parser(
        "compare",
        help="Compare grouped campaign cases",
        description="Group campaign cases by safe summary metrics.",
    )
    campaign_compare.add_argument(
        "case_dir",
        nargs="?",
        default=Path.cwd(),
        type=Path,
        help="Campaign root or case directory (default: current directory)",
    )
    campaign_compare.add_argument("--group-by", choices=["speed"], default="speed")
    campaign_compare.add_argument("--glob", default="*", help="Case directory glob under case_dir")
    campaign_compare.add_argument(
        "--summary-csv",
        default=None,
        type=Path,
        help="Read case paths from a campaign summary CSV",
    )
    _add_table_flag(campaign_compare)
    campaign_compare.add_argument("--json", action="store_true", help="Print result as JSON")
    campaign_compare.set_defaults(func=_knife_campaign_compare)

    plot_criteria = knife_sub.add_parser("plot-criteria", help="Alias of plot criteria")
    plot_criteria.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(plot_criteria)
    plot_criteria.add_argument("--json", action="store_true")
    plot_criteria.set_defaults(func=_plot_metrics)

    _add_plugin_knife_commands(knife_sub)


def _add_plugin_knife_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    registry = discover_plugins()
    for name, command in sorted(registry.knife_commands.items()):
        spec_fn = getattr(command, "command_spec", None)
        if not callable(spec_fn):
            registry.errors.append(f"{name}: plugin command lacks command_spec()")
            continue
        try:
            build_spec_parser(subparsers, spec_fn())
        except argparse.ArgumentError as exc:
            registry.errors.append(f"{name}: {exc}")
