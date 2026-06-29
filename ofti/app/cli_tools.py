from __future__ import annotations

import sys
from collections.abc import Mapping
from types import ModuleType
from typing import TYPE_CHECKING

from ofti.app.cli_adapters import bundle as _bundle_adapter
from ofti.app.cli_adapters import knife as _knife_adapter
from ofti.app.cli_adapters import main as _main_adapter
from ofti.app.cli_adapters import plot as _plot_adapter
from ofti.app.cli_adapters import run as _run_adapter
from ofti.app.cli_adapters import watch as _watch_adapter
from ofti.app.cli_help import _output_mode_conflict
from ofti.core import run_manifest as manifest_ops
from ofti.tools import parallel_resize_service, status_render_service, table_render_service
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import plot as plot_ops
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.cli_tools import watch as watch_ops

build_parser = _main_adapter.build_parser
ofti_version = _main_adapter.ofti_version

if TYPE_CHECKING:
    # `_export_private_handlers` copies these handlers into the module namespace
    # at runtime; re-export them statically so type checkers (and callers/tests
    # that reach them through `cli_tools`) can see them. F401 is ignored for this
    # file in pyproject.toml because these are intentional re-exports.
    from ofti.app.cli_adapters.knife import (
        _knife_adopt,
        _knife_campaign_compare,
        _knife_campaign_list,
        _knife_campaign_rank,
        _knife_campaign_status,
        _knife_compare,
        _knife_converge,
        _knife_criteria,
        _knife_current,
        _knife_doctor,
        _knife_eta,
        _knife_initials,
        _knife_manifest_restore,
        _knife_manifest_verify,
        _knife_manifest_write,
        _knife_preflight,
        _knife_report,
        _knife_set,
        _knife_stability,
        _knife_status,
    )
    from ofti.app.cli_adapters.plot import _plot_metrics, _plot_residuals
    from ofti.app.cli_adapters.run import _run_solver_execute, _run_tool
    from ofti.app.cli_adapters.watch import (
        _watch_external,
        _watch_interval,
        _watch_jobs,
        _watch_json_payload,
        _watch_output,
        _watch_pause,
        _watch_resume,
        _watch_start,
        _watch_stop,
    )


def _export_private_handlers(module: ModuleType) -> None:
    for name in dir(module):
        if name.startswith("_") and not name.startswith("__"):
            globals()[name] = getattr(module, name)


for _module in (
    _bundle_adapter,
    _knife_adapter,
    _plot_adapter,
    _watch_adapter,
    _run_adapter,
    _main_adapter,
):
    _export_private_handlers(_module)

_ORIG_WATCH_LOG = _watch_adapter._watch_log
_ORIG_WATCH_ATTACH = _watch_adapter._watch_attach
_ORIG_PRINT_WATCH_EXTERNAL_ATTACH = _watch_adapter._print_watch_external_attach
time = _watch_adapter.time


def _run_solver_with_mode(args, *, background: bool) -> int:
    _run_adapter._parallel_setup_payload = globals()["_parallel_setup_payload"]
    return int(_run_adapter._run_solver_with_mode(args, background=background))


def _watch_run(args) -> int:
    return int(globals()["_run_solver_with_mode"](args, background=False))


def _watch_log(args) -> int:
    _watch_adapter._watch_log = _ORIG_WATCH_LOG
    _watch_adapter._follow_log_path = globals()["_follow_log_path"]
    return int(_ORIG_WATCH_LOG(args))


def _watch_attach(args) -> int:
    _watch_adapter._watch_log = globals()["_watch_log"]
    try:
        return int(_ORIG_WATCH_ATTACH(args))
    finally:
        _watch_adapter._watch_log = _ORIG_WATCH_LOG


def _print_watch_external_attach(args, payload: Mapping[str, object]) -> int:
    _watch_adapter._follow_log_path = globals()["_follow_log_path"]
    return int(_ORIG_PRINT_WATCH_EXTERNAL_ATTACH(args, dict(payload)))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if bool(getattr(args, "version", False)):
        print(f"ofti {ofti_version()}")
        return 0
    if _output_mode_conflict(args):
        print("ofti: --json and --table cannot be used together", file=sys.stderr)
        return 2
    try:
        if args.func is _ORIG_WATCH_LOG:
            return int(globals()["_watch_log"](args))
        if args.func is _ORIG_WATCH_ATTACH:
            return int(globals()["_watch_attach"](args))
        return int(args.func(args))
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 2


__all__ = [
    "build_parser",
    "knife_ops",
    "main",
    "manifest_ops",
    "ofti_version",
    "parallel_resize_service",
    "plot_ops",
    "run_ops",
    "status_render_service",
    "table_render_service",
    "time",
    "watch_ops",
]

if __name__ == "__main__":
    raise SystemExit(main())
