from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

from ofti.app.cli_help import emit_json
from ofti.tools.cli_tools import run as run_ops


def build_queue_summary_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "queue-summary",
        help="Rebuild queue counters from a queue record or events journal",
        description=(
            "Read .ofti/queues/queue-*.json or queue-*.events.jsonl and rebuild "
            "summary counters from the append-only event journal."
        ),
    )
    parser.add_argument("path", type=Path, help="Queue record JSON or events JSONL path")
    parser.add_argument("--json", action="store_true", help="Print result as JSON")
    parser.set_defaults(func=_run_queue_summary)


def _run_queue_summary(args: argparse.Namespace) -> int:
    try:
        payload = run_ops.queue_summary_payload(cast("Path", args.path))
    except (TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if bool(getattr(args, "json", False)):
        emit_json(payload, args)
        return 0
    summary = cast("dict[str, object]", payload["summary"])
    print(f"queue_events_path={payload['queue_events_path']}")
    print(
        f"planned={summary['planned']} started={summary['started']} "
        f"finished={summary['finished']} failed_to_start={summary['failed_to_start']} "
        f"running={summary['running']}",
    )
    outcomes = cast("dict[str, object]", summary.get("outcomes", {}))
    if outcomes:
        print("outcomes=" + ",".join(f"{key}:{value}" for key, value in sorted(outcomes.items())))
    return 0


__all__ = ["build_queue_summary_parser"]
