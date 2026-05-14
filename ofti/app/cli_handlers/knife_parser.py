from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path

from ofti.tools import monitor_builder_service

Handler = Callable[[argparse.Namespace], int]


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



def _add_manifest_command(
    knife_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    handlers: Mapping[str, Handler],
    *,
    command_name: str,
    help_text: str,
    noun: str,
) -> None:
    command = knife_sub.add_parser(command_name, help=help_text)
    command.set_defaults(func=_help_handler(command))
    sub = command.add_subparsers(dest=f"{command_name}_command", required=False)

    write = sub.add_parser("write", help=f"Write a run {noun} for a case")
    write.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    write.add_argument("--solver", default=None)
    write.add_argument("--parallel", type=int, default=0)
    write.add_argument("--mpi", default=None)
    write.add_argument(
        "--sync-subdomains",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Recorded launch setting for parallel runs",
    )
    write.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Recorded launch setting for parallel runs",
    )
    write.add_argument(
        "--clean-processors",
        action="store_true",
        help="Recorded launch setting for parallel runs",
    )
    write.add_argument(
        "--receipt-file",
        "--manifest-file",
        dest="receipt_file",
        default=None,
        type=Path,
        help="Manifest/receipt JSON path (relative paths resolve from current working directory)",
    )
    write.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help=f"Copy system/, constant/, and 0/ alongside the {noun} for restore",
    )
    write.add_argument("--json", action="store_true")
    write.set_defaults(func=handlers["knife_receipt_write"])

    verify = sub.add_parser("verify", help=f"Verify current case inputs against a recorded {noun}")
    verify.add_argument("receipt", type=Path)
    verify.add_argument("--case", dest="case_dir", default=None, type=Path)
    _add_table_flag(verify)
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(func=handlers["knife_receipt_verify"])

    restore = sub.add_parser(
        "restore",
        help=f"Restore case inputs from a {noun} with recorded inputs",
    )
    restore.add_argument("receipt", type=Path)
    restore.add_argument("--to", dest="destination", required=True, type=Path)
    restore.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restore only selected roots: system, constant, 0 (repeatable or comma-separated)",
    )
    restore.add_argument(
        "--skip",
        action="append",
        default=[],
        help="Skip selected roots: system, constant, 0 (repeatable or comma-separated)",
    )
    restore.add_argument("--json", action="store_true")
    restore.set_defaults(func=handlers["knife_receipt_restore"])

def add_parser(
    groups: argparse._SubParsersAction[argparse.ArgumentParser],
    handlers: Mapping[str, Handler],
) -> None:
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
    doctor.set_defaults(func=handlers["knife_doctor"])

    lint = knife_sub.add_parser(
        "lint",
        help="Run read-only Case Doctor Pro lint checks",
    )
    lint.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(lint)
    lint.add_argument("--json", action="store_true")
    lint.set_defaults(func=handlers["knife_lint"])

    changes = knife_sub.add_parser(
        "changes",
        help="Show read-only pending case dictionary changes",
    )
    changes.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(changes)
    changes.add_argument("--json", action="store_true")
    changes.set_defaults(func=handlers["knife_changes"])

    preflight = knife_sub.add_parser("preflight", help="Check basic case/run prerequisites")
    preflight.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(preflight)
    preflight.add_argument("--json", action="store_true")
    preflight.set_defaults(func=handlers["knife_preflight"])

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
    compare.set_defaults(func=handlers["knife_compare"])

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
    copy.set_defaults(func=handlers["knife_copy"])

    _add_manifest_command(
        knife_sub,
        handlers,
        command_name="manifest",
        help_text="Write, verify, and restore immutable run manifests",
        noun="manifest",
    )
    _add_manifest_command(
        knife_sub,
        handlers,
        command_name="receipt",
        help_text="Legacy alias for `knife manifest`",
        noun="receipt",
    )

    initials = knife_sub.add_parser(
        "initials",
        help="Show initial internal fields and boundary conditions",
    )
    initials.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(initials)
    initials.add_argument("--json", action="store_true")
    initials.set_defaults(func=handlers["knife_initials"])

    captain_deck = knife_sub.add_parser(
        "captains-deck",
        help="Read-only Captains Deck summary: DNA, scopes, mesh radar, resources",
    )
    captain_deck.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    captain_deck.add_argument("--tail-bytes", type=int, default=None)
    _add_table_flag(captain_deck)
    captain_deck.add_argument("--json", action="store_true")
    captain_deck.set_defaults(func=handlers["knife_captains_deck"])

    dna = knife_sub.add_parser("dna", help="Show read-only case DNA and setup fingerprint")
    dna.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    dna.add_argument("--tail-bytes", type=int, default=None)
    _add_table_flag(dna)
    dna.add_argument("--json", action="store_true")
    dna.set_defaults(func=handlers["knife_dna"])

    scopes = knife_sub.add_parser("scopes", help="Show read-only Captains Deck mission scopes")
    scopes.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(scopes)
    scopes.add_argument("--json", action="store_true")
    scopes.set_defaults(func=handlers["knife_scopes"])

    monitors = knife_sub.add_parser(
        "monitors",
        help="Plan or write a functionObject monitor include file",
        description=(
            "Create a small system/controlDict.functions include file for safe live "
            "monitoring. Use --diff first, then --write when the plan is acceptable."
        ),
    )
    monitors.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    monitors.add_argument(
        "--monitor",
        action="append",
        choices=sorted(monitor_builder_service.SUPPORTED_MONITORS),
        help="Monitor to include; repeatable. Defaults to residuals and courant.",
    )
    monitors.add_argument("--write", action="store_true", help="Write system/controlDict.functions")
    monitors.add_argument("--diff", action="store_true", help="Show the proposed file diff")
    _add_table_flag(monitors)
    monitors.add_argument("--json", action="store_true")
    monitors.set_defaults(func=handlers["knife_monitors"])

    mesh_radar = knife_sub.add_parser("mesh-radar", help="Show read-only checkMesh radar")
    mesh_radar.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(mesh_radar)
    mesh_radar.add_argument("--json", action="store_true")
    mesh_radar.set_defaults(func=handlers["knife_mesh_radar"])

    resource = knife_sub.add_parser("resource", help="Show read-only disk/log resource watch")
    resource.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(resource)
    resource.add_argument("--json", action="store_true")
    resource.set_defaults(func=handlers["knife_resource"])

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
    status.set_defaults(func=handlers["knife_status"])

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
    current.set_defaults(func=handlers["knife_current"])

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
    adopt.set_defaults(func=handlers["knife_adopt"])

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
    case_status.set_defaults(func=handlers["knife_status"])

    set_cmd = knife_sub.add_parser("set", help="Set dictionary entry value")
    set_cmd.add_argument("case_dir", type=Path)
    set_cmd.add_argument("file", help="Dictionary path relative to case, e.g. system/controlDict")
    set_cmd.add_argument("key", help="Entry key, e.g. application")
    set_cmd.add_argument("value", nargs="+", help="Entry value text")
    set_cmd.add_argument("--json", action="store_true", help="Print result as JSON")
    set_cmd.set_defaults(func=handlers["knife_set"])

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
        "--write-manifest",
        dest="write_receipt",
        action="store_true",
        help="Write immutable launch manifest under ./runs/",
    )
    launch.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the receipt for restore",
    )
    launch.add_argument(
        "--receipt-file",
        "--manifest-file",
        dest="receipt_file",
        default=None,
        type=Path,
        help="Manifest/receipt JSON path (relative paths resolve from current working directory)",
    )
    launch.add_argument("--json", action="store_true", help="Print result as JSON")
    launch.set_defaults(func=handlers["watch_start"])

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
    run.set_defaults(func=handlers["watch_start"])

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
    stop.set_defaults(func=handlers["knife_stop"])

    pause = knife_sub.add_parser("pause", help="Alias of watch pause")
    pause.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    pause.add_argument("--job-id", default=None)
    pause.add_argument("--name", default=None)
    pause.add_argument("--all", action="store_true")
    pause.add_argument("--json", action="store_true")
    pause.set_defaults(func=handlers["watch_pause"])

    resume = knife_sub.add_parser("resume", help="Alias of watch resume")
    resume.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    resume.add_argument("--job-id", default=None)
    resume.add_argument("--name", default=None)
    resume.add_argument("--all", action="store_true")
    resume.add_argument("--json", action="store_true")
    resume.set_defaults(func=handlers["watch_resume"])

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
    converge.set_defaults(func=handlers["knife_converge"])

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
    stability.set_defaults(func=handlers["knife_stability"])

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
    criteria.set_defaults(func=handlers["knife_criteria"])

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
    eta.set_defaults(func=handlers["knife_eta"])

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
    report.set_defaults(func=handlers["knife_report"])

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
    campaign_list.set_defaults(func=handlers["knife_campaign_list"])

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
    campaign_status.set_defaults(func=handlers["knife_campaign_status"])

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
    campaign_rank.set_defaults(func=handlers["knife_campaign_rank"])

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
    campaign_stop.set_defaults(func=handlers["knife_campaign_stop"])

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
    campaign_keep.set_defaults(func=handlers["knife_campaign_keep"])

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
    campaign_compare.set_defaults(func=handlers["knife_campaign_compare"])

    plot_criteria = knife_sub.add_parser("plot-criteria", help="Alias of plot criteria")
    plot_criteria.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(plot_criteria)
    plot_criteria.add_argument("--json", action="store_true")
    plot_criteria.set_defaults(func=handlers["plot_metrics"])
