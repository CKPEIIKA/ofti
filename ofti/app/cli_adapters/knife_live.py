from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from ofti.app.cli_adapters import knife_deck as knife_deck_cli
from ofti.tools import status_render_service, table_render_service
from ofti.tools.cli_tools import knife as knife_ops


def _knife_status(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.status_payload(
            args.case_dir,
            lightweight=knife_deck_cli._knife_use_lightweight_mode(args),
            tail_bytes=knife_deck_cli._tail_bytes_with_cpu_mode(args),
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
