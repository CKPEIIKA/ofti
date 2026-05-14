from __future__ import annotations

import argparse
import json

from ofti.tools import captains_deck_service, monitor_builder_service, table_render_service
from ofti.tools.cli_tools import knife as knife_ops

_EASY_ON_CPU_TAIL_BYTES = 256 * 1024
_EASY_ON_CPU_MIN_POLL_INTERVAL = 1.0

def _knife_initials(args: argparse.Namespace) -> int:
    payload = knife_ops.initials_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.initials_table_lines(payload)))
        return 0
    print(f"case={payload['case']}")
    print(f"initial_dir={payload['initial_dir']}")
    print(f"fields={payload['field_count']} patches={payload['patch_count']}")
    for field in payload["fields"]:
        print(f"\n[{field['name']}]")
        print(f"internalField={field['internal_field'] or '<missing>'}")
        boundary = field.get("boundary", {})
        if not boundary:
            print("boundary=<none>")
            continue
        for patch in sorted(boundary):
            row = boundary[patch]
            print(
                f"- {patch}: type={row.get('type') or 'missing'} "
                f"value={row.get('value') or ''}",
            )
    return 0


def _knife_captains_deck(args: argparse.Namespace) -> int:
    payload = captains_deck_service.captains_deck_payload(
        args.case_dir,
        tail_bytes=_tail_bytes_with_cpu_mode(args),
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("\n".join(table_render_service.captains_deck_table_lines(payload)))
    return 0


def _knife_dna(args: argparse.Namespace) -> int:
    payload = captains_deck_service.case_dna_payload(
        args.case_dir,
        tail_bytes=_tail_bytes_with_cpu_mode(args),
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("\n".join(table_render_service.case_dna_table_lines(payload)))
    return 0


def _knife_scopes(args: argparse.Namespace) -> int:
    payload = captains_deck_service.mission_scope_payload(args.case_dir)
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("\n".join(table_render_service.scope_table_lines(payload)))
    return 0


def _knife_monitors(args: argparse.Namespace) -> int:
    payload = monitor_builder_service.monitor_builder_payload(
        args.case_dir,
        monitors=getattr(args, "monitor", None),
        write=bool(getattr(args, "write", False)),
        include_diff=bool(getattr(args, "diff", False)),
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("\n".join(table_render_service.monitor_builder_table_lines(payload)))
    return 0


def _knife_mesh_radar(args: argparse.Namespace) -> int:
    payload = captains_deck_service.mesh_radar_payload(args.case_dir)
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("\n".join(table_render_service.mesh_radar_table_lines(payload)))
    return 0


def _knife_resource(args: argparse.Namespace) -> int:
    payload = captains_deck_service.resource_watch_payload(args.case_dir)
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("\n".join(table_render_service.resource_watch_table_lines(payload)))
    return 0


def _knife_use_lightweight_mode(args: argparse.Namespace) -> bool:
    return not bool(getattr(args, "full", False))


def _tail_bytes_with_cpu_mode(args: argparse.Namespace) -> int | None:
    explicit = getattr(args, "tail_bytes", None)
    if explicit is not None:
        return int(explicit)
    if bool(getattr(args, "easy_on_cpu", False)):
        return _EASY_ON_CPU_TAIL_BYTES
    return None


def _interval_with_cpu_mode(args: argparse.Namespace, interval: float) -> float:
    value = float(interval)
    if value <= 0:
        value = 0.25
    if bool(getattr(args, "easy_on_cpu", False)):
        value = max(value, _EASY_ON_CPU_MIN_POLL_INTERVAL)
    return value
