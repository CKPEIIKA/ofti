from __future__ import annotations

import argparse
import sys
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
from ofti.app.cli_help import (
    Handler,
    _fill_missing_help,
    _help_handler,
    _output_mode_conflict,
)


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


_KNIFE_HANDLER_NAMES = ["adopt", "campaign_compare", "campaign_keep", "campaign_list", "campaign_rank", "campaign_status", "campaign_stop", "changes", "captains_deck", "compare", "converge", "copy", "criteria", "current", "dna", "doctor", "eta", "initials", "lint", "mesh_radar", "monitors", "preflight", "receipt_restore", "receipt_verify", "receipt_write", "report", "resource", "scopes", "set", "stability", "status", "stop"]  # noqa: E501


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
