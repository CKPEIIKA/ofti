from __future__ import annotations

import argparse
import json
import sys
import time
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


def _watch_cases(args: argparse.Namespace) -> int:
    if bool(getattr(args, "follow", False)) and bool(getattr(args, "json", False)):
        print("ofti: --json cannot be used with --follow", file=sys.stderr)
        return 2
    if not bool(getattr(args, "follow", False)):
        payload = _watch_cases_payload(args)
        if bool(getattr(args, "json", False)):
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        print("\n".join(table_render_service.live_cases_table_lines(payload)))
        return 0

    interval = _interval_with_cpu_mode(args, max(float(getattr(args, "interval", 2.0)), 0.25))
    try:
        while True:
            payload = _watch_cases_payload(args)
            print("\033[H\033[J", end="")
            print("\n".join(table_render_service.live_cases_table_lines(payload)))
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


def _watch_cases_payload(args: argparse.Namespace) -> dict[str, object]:
    payload = run_ops.status_set_payload(
        set_dir=getattr(args, "set_dir", Path.cwd()),
        explicit_cases=list(getattr(args, "cases", [])),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        lightweight=not bool(getattr(args, "full", False)),
        tail_bytes=_tail_bytes_with_cpu_mode(args),
    )
    rows = sorted(
        payload.get("rows", []),
        key=lambda row: _watch_case_sort_key(row, str(getattr(args, "sort", "state"))),
    )
    payload["rows"] = rows
    payload["sort"] = getattr(args, "sort", "state")
    payload["group_state"] = bool(getattr(args, "group_state", False))
    return payload


def _watch_case_sort_key(row: object, sort_by: str) -> tuple[object, ...]:
    data = cast("dict[str, object]", row) if isinstance(row, dict) else {}
    state_rank = {"running": 0, "queued": 1, "failed": 2, "unknown": 3, "done": 4}
    state = str(data.get("state") or "unknown")
    case = str(data.get("case") or "")
    if sort_by == "case":
        return (case,)
    if sort_by == "latest":
        return (_none_last(data.get("latest_time")), case)
    if sort_by == "eta":
        return (_none_last(data.get("eta_seconds")), case)
    if sort_by == "jobs":
        return (-int(data.get("jobs_running") or 0), state_rank.get(state, 99), case)
    return (state_rank.get(state, 99), case)


def _none_last(value: object) -> tuple[int, float, str]:
    if value is None:
        return (1, 0.0, "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    try:
        return (0, float(str(value)), str(value))
    except ValueError:
        return (0, 0.0, str(value))

