from __future__ import annotations

import argparse
from pathlib import Path

from ofti.app.cli_help import _add_table_flag, emit_json
from ofti.tools import checkpoint_service


def build_restart_plan_parser(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = commands.add_parser(
        "restart-plan",
        help="Inspect a decomposed case and print a safe restart plan",
        description=(
            "Read processor checkpoints and MPI sizing without mutating the case. "
            "The command reports the latest common time and any partial newer writes."
        ),
    )
    parser.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    parser.add_argument(
        "--from",
        dest="expected_processors",
        type=int,
        default=None,
        help="Expected current MPI size (default: decomposeParDict or processor count)",
    )
    parser.add_argument(
        "--to",
        dest="target_processors",
        type=int,
        default=None,
        help="Optional target MPI size to include in the plan",
    )
    _add_table_flag(parser)
    parser.add_argument("--json", action="store_true", help="Print result as JSON")
    parser.set_defaults(func=_run_restart_plan)


def _run_restart_plan(args: argparse.Namespace) -> int:
    payload = checkpoint_service.restart_plan_payload(
        args.case_dir,
        expected_processors=getattr(args, "expected_processors", None),
        target_processors=getattr(args, "target_processors", None),
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload, args)
        return 0 if payload["safe_to_apply"] else 1
    mpi = payload["mpi"]
    print(
        f"case={payload['case']} safe_to_apply={payload['safe_to_apply']} "
        f"latest_common_time={payload['latest_common_time']}",
    )
    print(
        f"mpi actual={mpi['actual']} configured={mpi['configured']} "
        f"expected={mpi['expected']} target={mpi['target']} consistent={mpi['consistent']}",
    )
    partial = payload["partial_newer_times"]
    print(f"partial_newer_times={','.join(str(row['time']) for row in partial) or 'none'}")
    for index, row in enumerate(payload["plan"], 1):
        detail = row.get("command") or row.get("entries") or row.get("value")
        print(f"{index}. {row['action']}: {detail}")
    return 0 if payload["safe_to_apply"] else 1
