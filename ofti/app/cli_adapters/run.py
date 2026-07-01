from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

from ofti.app.cli_adapters.common import (
    interval_with_cpu_mode,
    parse_env_assignments,
    planned_manifest_path,
    solver_name_for_manifest,
    tail_bytes_with_cpu_mode,
)
from ofti.app.cli_adapters.run_queue_summary import build_queue_summary_parser
from ofti.app.cli_help import (
    _add_easy_on_cpu_flag,
    _add_table_flag,
    _help_handler,
    emit_json,
)
from ofti.core import run_manifest as manifest_ops
from ofti.core.field_diagnostics import split_field_list
from ofti.foam.config import get_config
from ofti.tools import parallel_resize_service, table_render_service
from ofti.tools.cli_tools import run as run_ops


def _configured_path(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    return Path(value).expanduser()


def _choice_default(value: str, choices: tuple[str, ...], fallback: str) -> str:
    return value if value in choices else fallback


def _build_run_parser(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    cfg = get_config()
    default_case_root = _configured_path(cfg.paths.case_root) or Path.cwd()
    default_parallel = max(0, int(cfg.run.default_parallel))
    default_queue_backend = _choice_default(
        cfg.queue.backend,
        ("process", "foamlib-async", "foamlib-slurm"),
        "process",
    )
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
    solver.add_argument("--parallel", type=int, default=default_parallel)
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
        "--write-manifest",
        "--write-receipt",
        dest="write_manifest",
        action="store_true",
        help="Write immutable launch manifest under ./runs/",
    )
    solver.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the manifest for restore",
    )
    solver.add_argument(
        "--manifest-file",
        "--receipt-file",
        dest="manifest_file",
        default=None,
        type=Path,
        help="Manifest JSON path (relative paths resolve from current working directory)",
    )
    solver.add_argument("--dry-run", action="store_true")
    solver.add_argument("--json", action="store_true", help="Print result as JSON")
    solver.set_defaults(func=_run_solver)

    smoke = run_sub.add_parser(
        "smoke",
        help="Run a bounded solver smoke test on a copied case",
        description=(
            "Run a short solver smoke test. By default OFTI copies the case into "
            "an output directory, normalizes controlDict for a bounded run, writes "
            "log/summary artifacts, and leaves the source case untouched."
        ),
    )
    smoke.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    smoke.add_argument("--solver", default=None)
    smoke.add_argument("--iterations", type=int, default=20)
    smoke.add_argument(
        "--timeout",
        default="300s",
        help="Wall timeout, e.g. 30s, 5m, 1h (default: 300s)",
    )
    smoke.add_argument("--parallel", type=int, default=default_parallel)
    smoke.add_argument("--mpi", default=None)
    smoke.add_argument(
        "--out",
        dest="output_root",
        type=Path,
        default=_configured_path(cfg.paths.smoke_root),
    )
    smoke.add_argument("--in-place", action="store_true", help="Run in the source case")
    smoke.add_argument("--deltaT", dest="delta_t", type=float, default=None)
    smoke.add_argument(
        "--preserve-deltaT",
        action="store_true",
        help="Preserve existing deltaT instead of writing --deltaT/default",
    )
    smoke.add_argument(
        "--core-only",
        action="store_true",
        help="Disable functionObjects by writing an empty functions dictionary",
    )
    smoke.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step for --parallel > 1",
    )
    smoke.add_argument("--clean-processors", action="store_true")
    smoke.add_argument(
        "--physical",
        action="store_true",
        help="Run ofti knife physical on the smoke case after the solver exits",
    )
    smoke.add_argument(
        "--fields",
        action="append",
        default=None,
        help="Fields for --physical (comma-separated, repeatable)",
    )
    smoke.add_argument("--json", action="store_true", help="Print result as JSON")
    smoke.set_defaults(func=_run_smoke)

    resize = run_sub.add_parser(
        "resize-parallel",
        help="Safely stop, reconstruct, redecompose, and resume with a new MPI size",
        description=(
            "Safely resize a running/decomposed parallel case: writeNow, wait for stop, "
            "snapshot inputs, verify the latest complete processor time, reconstruct it, "
            "update decomposeParDict, decompose latest time, and optionally restart."
        ),
    )
    resize.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    resize.add_argument(
        "--to",
        dest="to_ranks",
        type=int,
        required=True,
        help="New MPI rank count",
    )
    resize.add_argument(
        "--from",
        dest="from_ranks",
        type=int,
        default=None,
        help="Expected current rank count",
    )
    resize.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without changing files",
    )
    resize.add_argument(
        "--no-start",
        dest="start",
        action="store_false",
        help="Do not restart solver after decompose",
    )
    resize.add_argument(
        "--no-write-now",
        dest="write_now",
        action="store_false",
        help="Skip live writeNow request before reconstructing processor results",
    )
    resize.add_argument(
        "--force-stop",
        action="store_true",
        help="TERM tracked jobs if writeNow does not stop in time",
    )
    resize.add_argument(
        "--clean-processors",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Remove old processor* directories before redecompose",
    )
    resize.add_argument(
        "--stop-timeout",
        type=float,
        default=45.0,
        help="Seconds to wait for writeNow stop",
    )
    _add_table_flag(resize)
    resize.add_argument("--json", action="store_true", help="Print result as JSON")
    resize.set_defaults(func=_run_resize_parallel)

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
    matrix.add_argument("--parallel", type=int, default=default_parallel)
    matrix.add_argument("--mpi", default=None)
    matrix.add_argument("--max-parallel", type=int, default=max(1, int(cfg.queue.max_parallel)))
    matrix.add_argument("--poll-interval", type=float, default=float(cfg.queue.poll_interval))
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
    parametric.add_argument("--parallel", type=int, default=default_parallel)
    parametric.add_argument("--mpi", default=None)
    parametric.add_argument("--max-parallel", type=int, default=max(1, int(cfg.queue.max_parallel)))
    parametric.add_argument("--poll-interval", type=float, default=float(cfg.queue.poll_interval))
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
    queue.add_argument("--set", dest="set_dir", default=default_case_root, type=Path)
    queue.add_argument("--glob", default="*")
    queue.add_argument("--summary-csv", default=None, type=Path)
    queue.add_argument("--solver", default=None)
    queue.add_argument("--parallel", type=int, default=default_parallel)
    queue.add_argument("--mpi", default=None)
    queue.add_argument(
        "--backend",
        choices=["process", "foamlib-async", "foamlib-slurm"],
        default=default_queue_backend,
        help="Queue backend for case launches",
    )
    queue.add_argument(
        "--max-parallel",
        type=int,
        default=max(1, int(cfg.queue.max_parallel)),
        help="Maximum cases running at once (default: config or 1, sequential queue)",
    )
    queue.add_argument("--poll-interval", type=float, default=float(cfg.queue.poll_interval))
    queue.add_argument(
        "--queue-root",
        default=_configured_path(cfg.queue.root or cfg.paths.queue_root),
        type=Path,
        help="Directory where .ofti/queues is written (default: common case root)",
    )
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

    build_queue_summary_parser(run_sub)

    status = run_sub.add_parser(
        "status",
        help="Show compact status table for a case set",
        description=(
            "Show a compact read-only status table for explicit cases or for "
            "cases discovered under --set/--glob."
        ),
    )
    status.add_argument("cases", nargs="*", type=Path, help="Explicit case directories")
    status.add_argument(
        "--set",
        dest="set_dir",
        default=Path.cwd(),
        type=Path,
        help="Case-set root used when explicit cases are omitted",
    )
    status.add_argument("--glob", default="*", help="Case directory glob under --set")
    status.add_argument(
        "--summary-csv",
        default=None,
        type=Path,
        help="Read case paths from a campaign summary CSV",
    )
    status_mode = status.add_mutually_exclusive_group()
    status_mode.add_argument("--fast", action="store_true", help="Use lightweight status parsing")
    status_mode.add_argument("--full", action="store_true", help="Parse full logs (slower)")
    _add_easy_on_cpu_flag(status)
    status.add_argument(
        "--tail-bytes",
        type=int,
        default=None,
        help="Max solver log bytes to parse",
    )
    _add_table_flag(status)
    status.add_argument("--json", action="store_true", help="Print result as JSON")
    status.set_defaults(func=_run_status)

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
        poll_interval = interval_with_cpu_mode(args, float(getattr(args, "poll_interval", 0.25)))
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
        emit_json(payload, args)
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
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload, args)
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
    poll_interval = interval_with_cpu_mode(args, float(getattr(args, "poll_interval", 0.25)))
    explicit_cases = list(getattr(args, "cases", []))
    cases = run_ops.resolve_case_set(
        set_dir=args.set_dir,
        explicit_cases=explicit_cases,
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
        queue_root=_queue_root_for_args(args, explicit_cases=bool(explicit_cases)),
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload, args)
        return 0 if bool(payload.get("ok", True)) else 1
    print(
        f"count={payload['count']} max_parallel={payload['max_parallel']} "
        f"backend={payload.get('backend', 'process')} dry_run={payload['dry_run']}",
    )
    print(
        f"started={len(payload['started'])} finished={len(payload['finished'])} "
        f"failed_to_start={len(payload['failed_to_start'])}",
    )
    if payload.get("queue_path"):
        print(f"queue_path={payload['queue_path']}")
    for row in payload["finished"]:
        print(
            f"- {row['case']}: outcome={row.get('outcome', '-')} "
            f"state={row['state']} reason={row.get('stop_reason', '-')} "
            f"latest_time={row['latest_time']}",
        )
    if payload["failed_to_start"]:
        for row in payload["failed_to_start"]:
            print(f"failed {row['case']}: {row['error']}")
    return 0 if bool(payload.get("ok", True)) else 1


def _queue_root_for_args(args: argparse.Namespace, *, explicit_cases: bool) -> Path | None:
    queue_root = getattr(args, "queue_root", None)
    if queue_root is not None:
        return cast("Path", queue_root)
    return None if explicit_cases else cast("Path", args.set_dir)


def _run_smoke(args: argparse.Namespace) -> int:
    try:
        timeout = run_ops.parse_duration_seconds(getattr(args, "timeout", "300s"))
        payload = run_ops.smoke_payload(
            args.case_dir,
            solver=getattr(args, "solver", None),
            iterations=int(getattr(args, "iterations", 20)),
            timeout=timeout,
            parallel=int(getattr(args, "parallel", 0)),
            mpi=getattr(args, "mpi", None),
            output_root=getattr(args, "output_root", None),
            in_place=bool(getattr(args, "in_place", False)),
            delta_t=getattr(args, "delta_t", None),
            preserve_delta_t=bool(getattr(args, "preserve_deltaT", False)),
            core_only=bool(getattr(args, "core_only", False)),
            prepare_parallel=bool(getattr(args, "prepare_parallel", True)),
            clean_processors=bool(getattr(args, "clean_processors", False)),
            run_physical=bool(getattr(args, "physical", False)),
            physical_fields=split_field_list(getattr(args, "fields", None)),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if bool(getattr(args, "json", False)):
        emit_json(payload, args)
        return 0 if bool(payload.get("ok")) else 1
    print(f"case={payload['case']}")
    print(f"solver={payload['solver']} ok={payload['ok']} returncode={payload['returncode']}")
    print(
        f"times_seen={len(cast('list[object]', payload['times_seen']))} "
        f"end_seen={payload['end_seen']}",
    )
    print(f"log={payload['log_path']}")
    print(f"summary={Path(str(payload['output_root'])) / 'summary.json'}")
    return 0 if bool(payload.get("ok")) else 1


def _run_status(args: argparse.Namespace) -> int:
    payload = run_ops.status_set_payload(
        set_dir=args.set_dir,
        explicit_cases=list(getattr(args, "cases", [])),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        lightweight=not bool(getattr(args, "full", False)),
        tail_bytes=tail_bytes_with_cpu_mode(args),
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload, args)
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

def _run_resize_parallel(args: argparse.Namespace) -> int:
    payload = parallel_resize_service.parallel_resize_payload(
        args.case_dir,
        to_ranks=int(args.to_ranks),
        from_ranks=getattr(args, "from_ranks", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        start=bool(getattr(args, "start", True)),
        write_now=bool(getattr(args, "write_now", True)),
        force_stop=bool(getattr(args, "force_stop", False)),
        clean_processors=bool(getattr(args, "clean_processors", True)),
        stop_timeout=float(getattr(args, "stop_timeout", 45.0)),
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload, args)
        return 0 if bool(payload.get("ok", False)) else 1
    if bool(getattr(args, "table", False)):
        _print_resize_table(payload)
        return 0 if bool(payload.get("ok", False)) else 1
    print(
        f"case={payload['case']} from={payload.get('from')} to={payload['to']} "
        f"dry_run={payload['dry_run']} ok={payload['ok']}",
    )
    for row in cast("list[dict[str, object]]", payload.get("steps", [])):
        details = _resize_step_details(row)
        print(f"{row.get('status', '-'):<8} {row.get('step', '-'):<18} {details}")
    if payload.get("input_snapshot_path"):
        print(f"snapshot={payload['input_snapshot_path']}")
    if payload.get("rollback"):
        print(f"rollback={payload['rollback']}")
    if payload.get("error"):
        print(f"error={payload['error']}", file=sys.stderr)
    return 0 if bool(payload.get("ok", False)) else 1

def _print_resize_table(payload: dict[str, object]) -> None:
    print("STEP               STATUS    DETAILS")
    for row in cast("list[dict[str, object]]", payload.get("steps", [])):
        print(
            f"{row.get('step', '-')!s:<18} "
            f"{row.get('status', '-')!s:<8} "
            f"{_resize_step_details(row)}",
        )
    if payload.get("rollback"):
        print(f"\nRollback: {payload['rollback']}")

def _resize_step_details(row: dict[str, object]) -> str:
    parts: list[str] = []
    for key in (
        "command",
        "output",
        "latest",
        "latest_time_before",
        "latest_time_after",
        "pid",
        "log_path",
        "error",
    ):
        value = row.get(key)
        if value not in {None, ""}:
            parts.append(f"{key}={value}")
    if row.get("acknowledged") is not None:
        parts.append(f"acknowledged={row['acknowledged']}")
    if row.get("forced_stop"):
        parts.append(f"forced_stop={row['forced_stop']}")
    return " ".join(parts) or str(row.get("label", ""))

def _run_tool(args: argparse.Namespace) -> int:
    if args.list:
        return _run_tool_list(args)
    if not args.name:
        raise ValueError("tool name is required unless --list is used")
    resolved = run_ops.resolve_tool(args.case_dir, args.name)
    if resolved is None:
        return _run_tool_unknown(args)
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
        emit_json(payload, args)
        return result.returncode
    if result.pid is not None:
        print(f"Started {display_name} in background: pid={result.pid} log={result.log_path}")
        return 0
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.returncode

def _run_tool_list(args: argparse.Namespace) -> int:
    payload = run_ops.tool_catalog_payload(args.case_dir)
    if args.json:
        emit_json(payload, args)
    else:
        for name in payload["tools"]:
            print(name)
    return 0

def _run_tool_unknown(args: argparse.Namespace) -> int:
    names = run_ops.tool_catalog_names(args.case_dir)
    available = ", ".join(names)
    if args.json:
        emit_json(
            {
                "error": "unknown tool",
                "requested": args.name,
                "available": names,
            },
            args,
            file=sys.stderr,
        )
        return 1
    print(f"Unknown tool: {args.name}", file=sys.stderr)
    if available:
        print(f"Available tools: {available}", file=sys.stderr)
    return 1

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
    write_manifest = _write_manifest_enabled(args)
    manifest_path = (
        planned_manifest_path(args.case_dir, getattr(args, "manifest_file", None))
        if write_manifest
        else None
    )
    if getattr(args, "json", False):
        emit_json(
            {
                "case": str(Path(args.case_dir).resolve()),
                "name": display,
                "command": cmd_text,
                "dry_run": True,
                "sync_subdomains": sync_subdomains,
                "clean_processors": clean_processors,
                "prepare_parallel": prepare_parallel,
                "write_manifest": write_manifest,
                "record_inputs_copy": bool(getattr(args, "record_inputs_copy", False)),
                "manifest_path": str(manifest_path) if manifest_path is not None else None,
                "parallel_setup": parallel_setup,
            },
            args,
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
    if manifest_path is not None:
        print(f"# manifest: {manifest_path}")
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
    extra_env = parse_env_assignments(getattr(args, "env", []))
    write_manifest = _write_manifest_enabled(args)
    manifest_output = (
        planned_manifest_path(args.case_dir, getattr(args, "manifest_file", None))
        if write_manifest
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
    written_manifest: Path | None = None
    if write_manifest:
        written_manifest = manifest_ops.write_case_run_manifest(
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
            output=manifest_output,
            record_inputs_copy=bool(getattr(args, "record_inputs_copy", False)),
            solver_name=solver_name_for_manifest(cmd, parallel=parallel),
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
            "write_manifest": write_manifest,
            "record_inputs_copy": bool(getattr(args, "record_inputs_copy", False)),
            "manifest_path": str(written_manifest) if written_manifest is not None else None,
            "parallel_setup": parallel_setup,
            "returncode": result.returncode,
            "pid": result.pid,
            "log_path": str(result.log_path) if result.log_path else None,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "dry_run": False,
        }
        emit_json(payload, args)
        return result.returncode
    if result.pid is not None:
        print(f"Started {display} in background: pid={result.pid} log={result.log_path}")
        if written_manifest is not None:
            print(f"Manifest: {written_manifest}")
        return 0
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if written_manifest is not None:
        print(f"Manifest: {written_manifest}")
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

def _write_manifest_enabled(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "write_manifest", False)
        or getattr(args, "record_inputs_copy", False)
        or getattr(args, "manifest_file", None) is not None,
    )
