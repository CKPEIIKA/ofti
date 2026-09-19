from __future__ import annotations

import argparse
from typing import cast

from ofti.app.cli_help import emit_json
from ofti.tools.cli_tools import knife as knife_ops


def _knife_metric(args: argparse.Namespace) -> int:
    source = getattr(args, "source", None)
    field = getattr(args, "field", None)
    if bool(source) == bool(field):
        raise ValueError("provide exactly one table SOURCE or --field FIELD")
    payload = (
        _field_metric(args, str(field))
        if field
        else knife_ops.metric_payload(
            args.case_dir,
            str(source),
            options=knife_ops.MetricOptions(
                name=str(args.name or "metric"),
                coordinate_column=int(args.coordinate_column),
                value_column=int(args.value_column),
                threshold=getattr(args, "threshold", None),
                direction=str(args.direction),
                pick=str(args.pick),
                window=int(args.window),
                max_span=getattr(args, "max_span", None),
                scale=float(args.scale),
                offset=float(args.offset),
            ),
        )
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload, args)
        return 0 if bool(payload["ok"]) else 1
    if payload["mode"] == "field":
        _print_field_metric(payload)
        return 0 if bool(payload["ok"]) else 1
    print(f"name={payload['name']} value={payload['value']} coordinate={payload['coordinate']}")
    print(f"samples={payload['sample_count']} last_n_span={payload['last_n_span']} mature={payload['mature']}")
    print(f"maturity={payload['maturity_reason']}")
    for warning in cast("list[str]", payload["warnings"]):
        print(f"warning={warning}")
    return 0


def _field_metric(args: argparse.Namespace, field: str) -> dict[str, object]:
    return knife_ops.field_metric_payload(
        args.case_dir,
        field,
        options=knife_ops.FieldMetricOptions(
            time_name=str(args.time),
            patch=getattr(args, "patch", None),
            reduction=str(args.reduction),
            component=str(args.component),
            name=str(args.name) if args.name else None,
            scale=float(args.scale),
            offset=float(args.offset),
        ),
    )


def _print_field_metric(payload: dict[str, object]) -> None:
    location = f" patch={payload['patch']}" if payload["patch"] else ""
    print(
        f"name={payload['name']} field={payload['field']} time={payload['time']}{location} "
        f"{payload['reduction']}={payload['value']}",
    )
    print(
        f"component={payload['component']} values={payload['value_count']} "
        f"finite={payload['finite_count']} nonfinite={payload['nonfinite_count']}",
    )
    print(f"min={payload['min']} max={payload['max']} mean={payload['mean']}")
