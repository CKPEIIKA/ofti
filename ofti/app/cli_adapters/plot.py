from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ofti.app.cli_help import (
    _add_table_flag,
    _help_handler,
)
from ofti.tools import table_render_service
from ofti.tools.cli_tools import plot as plot_ops


def _build_plot_parser(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    plot = groups.add_parser(
        "plot",
        help="Log metrics and residual summaries",
        description="Log metrics and residual summaries.",
    )
    plot.set_defaults(func=_help_handler(plot))
    plot_sub = plot.add_subparsers(dest="command", required=False)

    metrics = plot_sub.add_parser("metrics", help="Summarize time/courant/execution metrics")
    metrics.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(metrics)
    metrics.add_argument("--json", action="store_true")
    metrics.set_defaults(func=_plot_metrics)

    criteria = plot_sub.add_parser("criteria", help="Alias of plot metrics")
    criteria.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    _add_table_flag(criteria)
    criteria.add_argument("--json", action="store_true")
    criteria.set_defaults(func=_plot_metrics)

    residuals = plot_sub.add_parser(
        "residuals",
        help="Summarize residual fields from a solver log",
    )
    residuals.add_argument("source", nargs="?", default=Path.cwd(), type=Path)
    residuals.add_argument("--field", action="append", default=[])
    residuals.add_argument("--limit", type=int, default=0)
    _add_table_flag(residuals)
    residuals.add_argument("--json", action="store_true")
    residuals.set_defaults(func=_plot_residuals)

def _plot_metrics(args: argparse.Namespace) -> int:
    try:
        payload = plot_ops.metrics_payload(args.source)
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.metrics_table_lines(payload)))
        return 0
    print(f"log={payload['log']}")
    print(f"time_steps={payload['times']['count']} last={payload['times']['last']}")
    print(f"courant_count={payload['courant']['count']} max={payload['courant']['max']}")
    exec_data = payload["execution_time"]
    print(f"execution_points={exec_data['count']} last={exec_data['last']}")
    if exec_data["delta_avg"] is not None:
        print(
            "step_time="
            f"min:{exec_data['delta_min']} avg:{exec_data['delta_avg']} "
            f"max:{exec_data['delta_max']}",
        )
    print(f"residual_fields={','.join(payload['residual_fields'])}")
    return 0

def _plot_residuals(args: argparse.Namespace) -> int:
    try:
        payload = plot_ops.residuals_payload(
            args.source,
            fields=list(args.field),
            limit=int(args.limit),
        )
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    if not payload["fields"]:
        print(f"No residuals found in {payload['log']}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.residual_payload_table_lines(payload)))
        return 0
    print(f"log={payload['log']}")
    for row in payload["fields"]:
        print(
            f"{row['field']}: count={row['count']} last={row['last']:.6g} "
            f"min={row['min']:.6g} max={row['max']:.6g}",
        )
    return 0

