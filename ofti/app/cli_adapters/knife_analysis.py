from __future__ import annotations

import argparse
import json
import sys
from typing import cast

from ofti.app.cli_adapters import knife_deck as knife_deck_cli
from ofti.core.field_diagnostics import split_field_list
from ofti.tools import table_render_service
from ofti.tools.cli_tools import knife as knife_ops


def _knife_converge(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.converge_payload(
            args.source,
            strict=bool(args.strict),
            shock_drift_limit=float(args.shock_drift_limit),
            drag_band_limit=float(args.drag_band_limit),
            mass_limit=float(args.mass_limit),
        )
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.converge_table_lines(payload)))
        return 0 if payload["ok"] else 1
    print(f"log={payload['log']}")
    print(
        f"shock drift={payload['shock']['drift']} limit={payload['shock']['limit']} "
        f"ok={payload['shock']['ok']}",
    )
    print(
        f"drag band={payload['drag']['band']} limit={payload['drag']['limit']} "
        f"ok={payload['drag']['ok']}",
    )
    print(
        "mass "
        f"last_abs_global={payload['mass']['last_abs_global']} limit={payload['mass']['limit']} "
        f"ok={payload['mass']['ok']}",
    )
    print(
        f"residuals flatline={payload['residuals']['flatline']} "
        f"fields={','.join(payload['residuals']['flatline_fields'])}",
    )
    print(
        f"thermo out_of_range_count={payload['thermo']['out_of_range_count']} "
        f"ok={payload['thermo']['ok']}",
    )
    print(f"strict={payload['strict']} strict_ok={payload['strict_ok']}")
    print(f"ok={payload['ok']}")
    return 0 if payload["ok"] else 1


def _knife_stability(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.stability_payload(
            args.source,
            pattern=str(args.pattern),
            tolerance=float(args.tolerance),
            window=int(args.window),
            startup_samples=int(args.startup_samples),
            comparator=str(args.comparator),
        )
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["status"] == "pass" else 1
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.stability_table_lines(payload)))
        return 0 if payload["status"] == "pass" else 1
    print(f"log={payload['log']}")
    print(f"pattern={payload['pattern']}")
    print(
        f"count={payload['count']} window={payload['window']} "
        f"delta={payload['window_delta']} tolerance={payload['tolerance']} "
        f"comparator={payload['comparator']}",
    )
    print(f"latest={payload['latest']}")
    print(f"status={payload['status']} unmet_reason={payload['unmet_reason']}")
    print(f"eta_seconds={payload['eta_seconds']}")
    return 0 if payload["status"] == "pass" else 1


def _knife_criteria(args: argparse.Namespace) -> int:
    payload = knife_ops.criteria_payload(
        args.case_dir,
        lightweight=knife_deck_cli._knife_use_lightweight_mode(args),
        tail_bytes=knife_deck_cli._tail_bytes_with_cpu_mode(args),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not payload.get("failed") else 1
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.criteria_payload_table_lines(payload)))
        return 0
    print(f"case={payload['case']}")
    print(
        f"criteria={payload['criteria_count']} pass={payload['passed']} "
        f"fail={payload['failed']} unknown={payload['unknown']}",
    )
    for row in payload["criteria"]:
        print(
            f"- {row['name']}: met={row['met']} value={row['value']} "
            f"tol={row['tol']} unmet={row['unmet']} source={row['source']}",
        )
    return 0


def _knife_eta(args: argparse.Namespace) -> int:
    payload = knife_ops.eta_payload(
        args.case_dir,
        mode=str(args.mode),
        lightweight=knife_deck_cli._knife_use_lightweight_mode(args),
        tail_bytes=knife_deck_cli._tail_bytes_with_cpu_mode(args),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.eta_table_lines(payload)))
        return 0
    print(f"case={payload['case']}")
    print(f"mode={payload['mode']}")
    print(f"eta_mode={payload.get('eta_mode')}")
    print(f"eta_reason={payload.get('eta_reason')}")
    print(f"eta_confidence={payload.get('eta_confidence')}")
    print(f"eta_seconds={payload['eta_seconds']}")
    print(f"eta_criteria_seconds={payload['eta_criteria_seconds']}")
    print(f"eta_end_time_seconds={payload['eta_end_time_seconds']}")
    return 0


def _knife_report(args: argparse.Namespace) -> int:
    fmt = "json" if bool(getattr(args, "json", False)) else str(getattr(args, "format", "json"))
    payload = knife_ops.report_payload(
        args.case_dir,
        lightweight=knife_deck_cli._knife_use_lightweight_mode(args),
        tail_bytes=knife_deck_cli._tail_bytes_with_cpu_mode(args),
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.report_table_lines(payload)))
        return 0
    if fmt == "md":
        print(knife_ops.report_markdown(payload))
        return 0
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _knife_campaign_list(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_list_payload(
        args.case_dir,
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_list_table_lines(payload)))
        return 0
    print(f"case={payload['case']}")
    print(f"count={payload['count']}")
    for case in payload["cases"]:
        print(f"- {case}")
    return 0


def _knife_campaign_status(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_status_payload(
        args.case_dir,
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        tail_bytes=int(getattr(args, "tail_bytes", 256 * 1024)),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_status_table_lines(payload)))
        return 0
    print(f"case={payload['case']}")
    print(f"count={payload['count']}")
    for row in payload["cases"]:
        print(
            f"- {row['case']}: running={row['running']} "
            f"criteria={row['criteria_met']}/{row['criteria_total']} "
            f"worst_ratio={row['criteria_worst_ratio']}",
        )
    return 0


def _knife_campaign_rank(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_rank_payload(
        args.case_dir,
        by=str(getattr(args, "by", "convergence")),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        tail_bytes=int(getattr(args, "tail_bytes", 256 * 1024)),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_rank_table_lines(payload)))
        return 0
    print(f"case={payload['case']}")
    print(f"count={payload['count']}")
    for idx, row in enumerate(payload["ranked"], start=1):
        print(
            f"{idx}. {row['case']} criteria={row['criteria_met']}/{row['criteria_total']} "
            f"ratio={row['criteria_worst_ratio']}",
        )
    return 0


def _knife_campaign_stop(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_stop_worst_payload(
        args.case_dir,
        worst=int(getattr(args, "worst", 0)),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        signal_name=str(getattr(args, "signal", "TERM")),
        dry_run=bool(getattr(args, "dry_run", False)),
        tail_bytes=int(getattr(args, "tail_bytes", 256 * 1024)),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        failed = [item for item in payload["actions"] if item.get("failed")]
        return 0 if not failed else 1
    print(f"case={payload['case']}")
    print(f"selected={payload['selected']} dry_run={payload['dry_run']}")
    for target in payload["targets"]:
        print(f"- {target}")
    failed = [item for item in payload["actions"] if item.get("failed")]
    return 0 if not failed else 1


def _knife_campaign_keep(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_keep_best_payload(
        args.case_dir,
        best=int(getattr(args, "best", 0)),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
        signal_name=str(getattr(args, "signal", "TERM")),
        dry_run=bool(getattr(args, "dry_run", False)),
        tail_bytes=int(getattr(args, "tail_bytes", 256 * 1024)),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        failed = [item for item in payload["actions"] if item.get("failed")]
        return 0 if not failed else 1
    print(f"case={payload['case']}")
    print(f"kept={payload['kept']} stopped={payload['stopped']} dry_run={payload['dry_run']}")
    for target in payload["targets"]:
        print(f"- {target}")
    failed = [item for item in payload["actions"] if item.get("failed")]
    return 0 if not failed else 1


def _knife_campaign_compare(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_compare_payload(
        args.case_dir,
        group_by=str(getattr(args, "group_by", "speed")),
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_compare_table_lines(payload)))
        return 0
    print(f"case={payload['case']}")
    print(f"group_by={payload['group_by']} groups={payload['group_count']}")
    for key, values in payload["groups"].items():
        print(f"- {key}: {len(values)} case(s)")
    print(f"comparisons={len(payload['comparisons'])}")
    return 0


def _knife_physical(args: argparse.Namespace) -> int:
    payload = knife_ops.physical_payload(
        args.case_dir,
        time_name=str(getattr(args, "time", "latest")),
        fields=split_field_list(list(getattr(args, "fields", []))),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok", False)) else 1
    print(f"case={payload['case']}")
    print(f"time={payload['time']} fields={payload['field_count']}")
    print(f"ok={payload['ok']} physical_ok={payload['physical_ok']}")
    for row in cast("list[dict[str, object]]", payload["fields"]):
        if not row.get("ok"):
            print(f"- {row['field']}: error={row.get('error')}")
            continue
        print(
            f"- {row['field']}: kind={row.get('kind')} count={row.get('count')} "
            f"min={row.get('min')} max={row.get('max')} "
            f"neg={row.get('negative_count')} nonfinite={row.get('nonfinite_count')}",
        )
    if payload.get("species_sum"):
        species = cast("dict[str, object]", payload["species_sum"])
        print(
            "sumY: "
            f"fields={','.join(cast('list[str]', species.get('fields', [])))} "
            f"min={species.get('min')} max={species.get('max')} "
            f"max_abs_deviation={species.get('max_abs_deviation')}",
        )
    for item in cast("list[dict[str, object]]", payload.get("violations", [])):
        print(f"violation: {item}")
    for item in cast("list[str]", payload.get("hard_errors", [])):
        print(f"hard_error: {item}")
    return 0 if bool(payload.get("ok", False)) else 1


def _knife_compare_fields(args: argparse.Namespace) -> int:
    payload = knife_ops.compare_fields_payload(
        args.left_case,
        args.right_case,
        time_name=str(getattr(args, "time", "latest")),
        fields=split_field_list(list(getattr(args, "fields", []))),
        preset=getattr(args, "preset", None),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok", False)) else 1
    print(f"left_case={payload['left_case']}")
    print(f"right_case={payload['right_case']}")
    print(f"time={payload['time']} fields={payload['field_count']} same={payload['same']}")
    for row in cast("list[dict[str, object]]", payload["fields"]):
        if not row.get("ok"):
            print(f"- {row['field']}: error={row.get('error')}")
            continue
        print(
            f"- {row['field']}: kind={row.get('kind')} count={row.get('count')} "
            f"maxAbs={row.get('max_abs')} maxRel={row.get('max_rel')} "
            f"nonfinite={row.get('nonfinite_pairs')}",
        )
    for item in cast("list[str]", payload.get("errors", [])):
        print(f"error: {item}")
    return 0 if bool(payload.get("ok", False)) else 1
