from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from ofti.app.cli_adapters.common import solver_name_for_manifest
from ofti.app.cli_adapters.plot import _plot_metrics
from ofti.app.cli_adapters.watch import _watch_pause, _watch_resume, _watch_start
from ofti.app.cli_help import (
    _EASY_ON_CPU_MIN_POLL_INTERVAL,
    _EASY_ON_CPU_TAIL_BYTES,
    _add_easy_on_cpu_flag,
    _add_table_flag,
    _help_handler,
)
from ofti.core import run_manifest as manifest_ops
from ofti.core.field_diagnostics import split_field_list
from ofti.plugins import discover_plugins
from ofti.tools import status_render_service, table_render_service
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import run as run_ops


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
    manifest_verify.add_argument("manifest", type=Path)
    manifest_verify.add_argument("--case", dest="case_dir", default=None, type=Path)
    manifest_verify.add_argument("--json", action="store_true")
    manifest_verify.set_defaults(func=_knife_manifest_verify)

    manifest_restore = manifest_sub.add_parser(
        "restore",
        help="Restore case inputs from a manifest with recorded input copies",
    )
    manifest_restore.add_argument("manifest", type=Path)
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
        try:
            command.add_parser(subparsers)
        except argparse.ArgumentError as exc:
            registry.errors.append(f"{name}: {exc}")

def _knife_doctor(args: argparse.Namespace) -> int:
    payload = knife_ops.doctor_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return knife_ops.doctor_exit_code(payload)
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.doctor_table_lines(payload)))
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
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.preflight_table_lines(payload)))
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
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.compare_table_lines(payload)))
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


def _knife_physical(args: argparse.Namespace) -> int:
    fields = split_field_list(list(getattr(args, "fields", []))) or []
    rules = list(getattr(args, "field_rules", []))
    profile_name = getattr(args, "profile", None)
    if profile_name:
        registry = discover_plugins()
        profile = registry.physical_profiles.get(str(profile_name))
        if profile is None:
            available = ", ".join(sorted(registry.physical_profiles)) or "none"
            print(
                f"ofti: physical profile '{profile_name}' is not available; "
                f"install a plugin that provides it (available: {available})",
                file=sys.stderr,
            )
            return 2
        profile_fields = [str(item) for item in profile.fields(args.case_dir)]
        fields = _unique_cli_items([*fields, *profile_fields])
        rules.extend(str(item) for item in profile.rules(args.case_dir))
    payload = knife_ops.physical_payload(
        args.case_dir,
        time_name=str(getattr(args, "time", "latest")),
        fields=fields or None,
        rules=rules,
        patch=getattr(args, "patch", None),
        out_dir=getattr(args, "out", None),
        report_stem="physical",
    )
    if profile_name:
        payload["profile"] = str(profile_name)
    return _print_physical_payload(payload, args)


def _unique_cli_items(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _print_physical_payload(payload: dict[str, object], args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return _physical_exit_code(payload, fail_on_bad=bool(getattr(args, "fail_on_bad", False)))
    print(f"case={payload['case']}")
    print(f"time={payload['time']} fields={payload['field_count']}")
    print(f"ok={payload['ok']} physical_ok={payload['physical_ok']}")
    if payload.get("outputs"):
        print(f"outputs={payload['outputs']}")
    for row in cast("list[dict[str, object]]", payload["fields"]):
        if not row.get("ok"):
            print(f"- {row['field']}: error={row.get('error')}")
            continue
        print(
            f"- {row['field']}: kind={row.get('kind')} count={row.get('count')} "
            f"min={row.get('min')} max={row.get('max')} "
            f"neg={row.get('negative_count')} nonfinite={row.get('nonfinite_count')}",
        )
    for item in cast("list[dict[str, object]]", payload.get("violations", [])):
        print(f"violation: {item}")
    for item in cast("list[str]", payload.get("hard_errors", [])):
        print(f"hard_error: {item}")
    return _physical_exit_code(payload, fail_on_bad=bool(getattr(args, "fail_on_bad", False)))


def _physical_exit_code(payload: dict[str, object], *, fail_on_bad: bool) -> int:
    if not bool(payload.get("ok", False)):
        return 1
    if fail_on_bad and not bool(payload.get("physical_ok", False)):
        return 1
    return 0


def _knife_compare_fields(args: argparse.Namespace) -> int:
    left_case = getattr(args, "reference", None) or getattr(args, "left_case", None)
    right_case = getattr(args, "candidate", None) or getattr(args, "right_case", None)
    if left_case is None or right_case is None:
        print(
            "compare-fields requires left/right cases or --reference/--candidate",
            file=sys.stderr,
        )
        return 2
    payload = knife_ops.compare_fields_payload(
        left_case,
        right_case,
        time_name=str(getattr(args, "time", "latest")),
        reference_time=getattr(args, "reference_time", None),
        candidate_time=getattr(args, "candidate_time", None),
        fields=split_field_list(list(getattr(args, "fields", []))),
        preset=getattr(args, "preset", None),
        patch=getattr(args, "patch", None),
        out_dir=getattr(args, "out", None),
        abs_tol=float(getattr(args, "abs_tol", 1e-300)),
        rel_tol=float(getattr(args, "rel_tol", 1e-12)),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok", False)) else 1
    print(f"left_case={payload['left_case']}")
    print(f"right_case={payload['right_case']}")
    print(f"time={payload['time']} fields={payload['field_count']} same={payload['same']}")
    if payload.get("outputs"):
        print(f"outputs={payload['outputs']}")
    for row in cast("list[dict[str, object]]", payload["fields"]):
        if not row.get("ok"):
            print(f"- {row['field']}: error={row.get('error')}")
            continue
        print(
            f"- {row['field']}: kind={row.get('kind')} count={row.get('count')} "
            f"maxAbs={row.get('abs_linf')} relL2={row.get('rel_l2')} "
            f"relLinfSig={row.get('rel_linf_significant')} "
            f"nonfinite={row.get('nonfinite_pairs')}",
        )
    for item in cast("list[str]", payload.get("errors", [])):
        print(f"error: {item}")
    return 0 if bool(payload.get("ok", False)) else 1


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

def _knife_manifest_write(args: argparse.Namespace) -> int:
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
    manifest_path = manifest_ops.write_case_run_manifest(
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
        output=getattr(args, "manifest_file", None),
        record_inputs_copy=bool(getattr(args, "record_inputs_copy", False)),
        solver_name=solver_name_for_manifest(cmd, parallel=parallel),
    )
    payload = {
        "case": str(Path(args.case_dir).resolve()),
        "command": command,
        "manifest": str(manifest_path),
        "recorded_inputs_copy": bool(getattr(args, "record_inputs_copy", False)),
        "ok": True,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_list_table_lines(payload)))
        return 0
    print(f"case={payload['case']}")
    print(f"command={payload['command']}")
    print(f"manifest={payload['manifest']}")
    print(f"recorded_inputs_copy={payload['recorded_inputs_copy']}")
    return 0

def _knife_manifest_verify(args: argparse.Namespace) -> int:
    payload = manifest_ops.verify_run_manifest(
        Path(args.manifest),
        case_path=getattr(args, "case_dir", None),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok")) else 1
    print(f"manifest={payload['manifest']}")
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

def _knife_manifest_restore(args: argparse.Namespace) -> int:
    payload = manifest_ops.restore_run_manifest(
        Path(args.manifest),
        Path(args.destination),
        only=getattr(args, "only", []),
        skip=getattr(args, "skip", []),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok")) else 1
    print(f"manifest={payload['manifest']}")
    print(f"destination={payload['destination']}")
    print(f"selected_roots={','.join(payload['selected_roots'])}")
    print(f"restored_manifest={payload['restored_manifest']}")
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
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.initials_table_lines(payload)))
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

def tail_bytes_with_cpu_mode(args: argparse.Namespace) -> int | None:
    explicit = getattr(args, "tail_bytes", None)
    if explicit is not None:
        return int(explicit)
    if bool(getattr(args, "easy_on_cpu", False)):
        return _EASY_ON_CPU_TAIL_BYTES
    return None

def interval_with_cpu_mode(args: argparse.Namespace, interval: float) -> float:
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
            tail_bytes=tail_bytes_with_cpu_mode(args),
        )
    except TypeError:
        payload = knife_ops.status_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.status_table_lines(payload)))
        return 0
    for line in status_render_service.case_status_lines(payload):
        print(line)
    return 0

def _knife_current(args: argparse.Namespace) -> int:
    payload = _knife_current_payload(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.current_table_lines(payload)))
        return 0
    _print_knife_current(payload)
    return 0

def _knife_current_payload(args: argparse.Namespace) -> Mapping[str, object]:
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

def _print_knife_current(payload: Mapping[str, object]) -> None:
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
    if payload.get("proc_access_warning"):
        print(f"proc_access_warning={payload['proc_access_warning']}")
    visibility = payload.get("process_visibility")
    if isinstance(visibility, dict) and visibility.get("message"):
        print(f"process_visibility={visibility['message']}")
    runs = list(payload.get("runs", []))
    if runs:
        _print_current_runs(runs)
    elif not payload["jobs"]:
        print("No tracked running jobs.")
    else:
        _print_current_jobs(list(payload["jobs"]))
    _print_current_untracked(list(payload["untracked_processes"]))

def _print_current_runs(runs: list[object]) -> None:
    print("runs:")
    for run_obj in runs:
        run = cast("dict[str, object]", run_obj)
        print(
            f"- {run.get('name', 'run')} pid={run.get('pid', '?')} "
            f"source={run.get('source')} status={run.get('status', 'unknown')} "
            f"launcher_pid={run.get('launcher_pid')} solvers={run.get('solver_pids', [])}",
        )

def _print_current_jobs(jobs: list[object]) -> None:
    print("tracked_jobs:")
    for job_obj in jobs:
        job = cast("dict[str, object]", job_obj)
        print(
            f"- {job.get('name', 'job')} pid={job.get('pid', '?')} "
            f"status={job.get('status', 'unknown')}",
        )

def _print_current_untracked(processes: list[object]) -> None:
    if not processes:
        print("untracked_solver_processes=none")
        return
    print("untracked_solver_processes:")
    for process_obj in processes:
        process = cast("dict[str, object]", process_obj)
        print(
            f"- pid={process['pid']} solver={process['solver']} "
            f"role={process.get('role')} case={process.get('case')} "
            f"launcher_pid={process.get('launcher_pid')} cmd={process['command']}",
        )

def _knife_current_scope_payload(
    case_dir: Path,
    *,
    live: bool,
    recursive: bool,
) -> Mapping[str, object]:
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
            method = row.get("method", "process")
            pgid = f" pgid={row['pgid']}" if row.get("pgid") is not None else ""
            print(
                f"- pid={row['pid']}{pgid} method={method} kind={row.get('kind', 'solver')} "
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
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.converge_table_lines(payload)))
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
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.stability_table_lines(payload)))
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
        tail_bytes=tail_bytes_with_cpu_mode(args),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not payload.get("failed") else 1
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.criteria_payload_table_lines(payload)))
        return 0
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
        tail_bytes=tail_bytes_with_cpu_mode(args),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.eta_table_lines(payload)))
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
        tail_bytes=tail_bytes_with_cpu_mode(args),
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.report_table_lines(payload)))
        return 0
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
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_list_table_lines(payload)))
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
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_status_table_lines(payload)))
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
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_rank_table_lines(payload)))
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
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_compare_table_lines(payload)))
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
