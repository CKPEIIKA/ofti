from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from textwrap import dedent
from typing import Any, cast

from ofti.app.cli_handlers import knife_analysis as knife_analysis_cli
from ofti.app.cli_handlers import knife_basic as knife_basic_cli
from ofti.app.cli_handlers import knife_deck as knife_deck_cli
from ofti.app.cli_handlers import knife_live as knife_live_cli
from ofti.app.cli_handlers import knife_parser as knife_cli
from ofti.app.cli_handlers import manifest as manifest_cli
from ofti.app.cli_handlers import plot as plot_cli
from ofti.app.cli_handlers import run as run_cli
from ofti.app.cli_handlers import watch as watch_cli

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
    # Backward-compatible alias.
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


def _output_mode_conflict(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False) and getattr(args, "table", False))


_HELP_BY_DEST = {
    "all": "Apply to all matching tracked jobs",
    "background": "Start the command in the background",
    "best": "Number of best-ranked cases to keep",
    "brief": "Use compact watcher output",
    "case_dir": "OpenFOAM case directory (default: current directory)",
    "cases": "Explicit case directories",
    "destination": "Destination path",
    "detailed": "Use detailed watcher output",
    "drag_band_limit": "Maximum allowed drag-band spread",
    "dry_run": "Print planned actions without applying them",
    "field": "Residual field to include (repeatable)",
    "follow": "Keep following the log for new lines",
    "format": "Output format",
    "glob": "Case directory glob",
    "group_state": "Group case monitor rows by state",
    "job_id": "Tracked job id from .ofti/jobs.json",
    "json": "Print result as JSON",
    "kind": "Tracked job kind filter",
    "left_case": "Left case directory",
    "limit": "Maximum residual rows per field (0 means no limit)",
    "lines": "Number of log lines to print",
    "list": "List available tools",
    "log_file": "Log file path for background execution",
    "mass_limit": "Maximum allowed mass-balance drift",
    "max_parallel": "Maximum number of cases to run at once",
    "mode": "ETA target mode",
    "mpi": "MPI launcher (default: mpirun/mpiexec)",
    "name": "Tool or tracked job name",
    "no_detach": "Run foreground even when background flags are present",
    "output": "Output verbosity",
    "output_root": "Directory for generated cases",
    "parallel": "Number of MPI ranks / subdomains (0 means serial)",
    "pid_file": "Write background process pid to this file",
    "poll_interval": "Seconds between queue status polls",
    "receipt": "Run receipt JSON file",
    "right_case": "Right case directory",
    "seconds": "Polling interval in seconds",
    "set_dir": "Case-set root used when explicit cases are omitted",
    "sort": "Sort case monitor rows",
    "shock_drift_limit": "Maximum allowed shock-position drift",
    "solver": "Solver override; defaults to controlDict application",
    "source": "Case directory or solver log path",
    "startup_samples": "Samples to ignore before stability checks",
    "summary_csv": "Read case paths from a campaign summary CSV",
    "tail_bytes": "Max solver log bytes to parse",
    "tolerance": "Required stability tolerance",
    "window": "Number of recent samples to inspect",
    "worst": "Number of worst-ranked cases to stop",
}


def _fill_missing_help(parser: argparse.ArgumentParser) -> None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for subparser in action.choices.values():
                _fill_missing_help(subparser)
            continue
        if action.dest == "help" or action.help is not None:
            continue
        action.help = _HELP_BY_DEST.get(action.dest, action.dest.replace("_", " ").capitalize())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofti",
        description=(
            "Non-interactive OFTI utilities.\n"
            "Use --json for machine output and --table for aligned diagnostics."
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
    _fill_missing_help(parser)
    return parser


def _build_knife_parser(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    knife_cli.add_parser(groups, _knife_handlers())


_KNIFE_HANDLER_NAMES = ["adopt", "campaign_compare", "campaign_keep", "campaign_list", "campaign_rank", "campaign_status", "campaign_stop", "changes", "cockpit", "compare", "converge", "copy", "criteria", "current", "dna", "doctor", "eta", "initials", "lint", "mesh_radar", "monitors", "preflight", "receipt_restore", "receipt_verify", "receipt_write", "report", "resource", "scopes", "set", "stability", "status", "stop"]  # noqa: E501


def _knife_handlers() -> dict[str, Handler]:
    handlers = {f"knife_{name}": _compat(f"_knife_{name}") for name in _KNIFE_HANDLER_NAMES}
    handlers.update({
        "plot_metrics": _compat("_plot_metrics"),
        "watch_pause": _compat("_watch_pause"),
        "watch_resume": _compat("_watch_resume"),
        "watch_start": _compat("_watch_start"),
    })
    return handlers


_build_plot_parser = plot_cli.add_parser


def _build_watch_parser(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    watch_cli.add_parser(groups, _watch_handlers())


def _watch_handlers() -> watch_cli.WatchHandlers:
    return watch_cli.WatchHandlers(
        jobs=_compat("_watch_jobs"),
        cases=_compat("_watch_cases"),
        log=_compat("_watch_log"),
        attach=_compat("_watch_attach"),
        start=_compat("_watch_start"),
        pause=_compat("_watch_pause"),
        resume=_compat("_watch_resume"),
        interval=_compat("_watch_interval"),
        output=_compat("_watch_output"),
        run=_compat("_watch_run"),
        stop=_compat("_watch_stop"),
        external=_compat("_watch_external"),
    )


def _build_run_parser(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run_cli.add_parser(groups, _run_handlers())


def _run_handlers() -> run_cli.RunHandlers:
    return run_cli.RunHandlers(
        tool=_compat("_run_tool"),
        resize_parallel=_compat("_run_resize_parallel"),
        solver=_compat("_run_solver"),
        matrix=_compat("_run_matrix"),
        parametric=_compat("_run_parametric"),
        queue=_compat("_run_queue"),
        status=_compat("_run_status"),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if bool(getattr(args, "version", False)):
        print(f"ofti {ofti_version()}")
        return 0
    if _output_mode_conflict(args):
        print("ofti: --json and --table cannot be used together", file=sys.stderr)
        return 2
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


_COMPAT_MODULES = (
    knife_basic_cli,
    knife_deck_cli,
    knife_live_cli,
    knife_analysis_cli,
    manifest_cli,
    plot_cli,
    watch_cli,
    run_cli,
)
_COMPAT_RENAMES = {
    "_plot_metrics": (plot_cli, "metrics_command"),
    "_plot_residuals": (plot_cli, "residuals_command"),
}
_MISSING = object()


def _compat_any(name: str) -> Any:
    value = globals().get(name, _MISSING)
    if value is not _MISSING:
        return value
    if renamed := _COMPAT_RENAMES.get(name):
        module, attr = renamed
        return getattr(module, attr)
    for module in _COMPAT_MODULES:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)


def _compat(name: str) -> Handler:
    return cast(Handler, _compat_any(name))


def __getattr__(name: str) -> object:
    return _compat_any(name)
