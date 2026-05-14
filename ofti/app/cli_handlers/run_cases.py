from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from ofti.tools import table_render_service
from ofti.tools.cli_tools import run as run_ops

_EASY_ON_CPU_TAIL_BYTES = 256 * 1024
_EASY_ON_CPU_MIN_POLL_INTERVAL = 1.0


def _use_easy_on_cpu_mode(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "easy_on_cpu", False))


def _tail_bytes_with_cpu_mode(args: argparse.Namespace) -> int | None:
    explicit = getattr(args, "tail_bytes", None)
    if explicit is not None:
        return int(explicit)
    if _use_easy_on_cpu_mode(args):
        return _EASY_ON_CPU_TAIL_BYTES
    return None


def _interval_with_cpu_mode(args: argparse.Namespace, interval: float) -> float:
    if not _use_easy_on_cpu_mode(args):
        return interval
    return max(float(interval), _EASY_ON_CPU_MIN_POLL_INTERVAL)


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
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.run_status_table_lines(payload)))
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

