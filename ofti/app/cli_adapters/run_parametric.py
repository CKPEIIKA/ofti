from __future__ import annotations

import argparse
from typing import cast

from ofti.app.cli_adapters.common import interval_with_cpu_mode
from ofti.app.cli_help import emit_json
from ofti.tools.cli_tools import run as run_ops


def _run_parametric(args: argparse.Namespace) -> int:
    poll_interval = interval_with_cpu_mode(args, float(getattr(args, "poll_interval", 0.25)))
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
        bundle_output=getattr(args, "bundle_output", None),
        bundle_name=getattr(args, "bundle_name", None),
        bundle_mesh=str(getattr(args, "bundle_mesh", "auto")),
        bundle_time=str(getattr(args, "bundle_time", "0")),
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload, args)
        return _queue_exit_code(payload)
    _print_parametric(payload)
    return _queue_exit_code(payload)


def _print_parametric(payload: dict[str, object]) -> None:
    print(f"case={payload['case']}")
    print(f"mode={payload['mode']} created={payload['created_count']} run_solver={payload['run_solver']}")
    for path in cast("list[str]", payload["created"]):
        print(f"- {path}")
    bundle = cast("dict[str, object] | None", payload.get("bundle"))
    if bundle:
        print(f"bundle_set={bundle['archive']}")
    queue = cast("dict[str, object] | None", payload.get("queue"))
    if queue:
        print(
            f"queue max_parallel={queue['max_parallel']} "
            f"backend={queue.get('backend', 'process')} "
            f"started={len(cast('list[object]', queue['started']))} "
            f"failed_to_start={len(cast('list[object]', queue['failed_to_start']))}",
        )


def _queue_exit_code(payload: dict[str, object]) -> int:
    queue = cast("dict[str, object] | None", payload.get("queue"))
    return 1 if queue and queue.get("ok") is False else 0
