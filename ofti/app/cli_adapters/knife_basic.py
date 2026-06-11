from __future__ import annotations

import argparse
import json
import sys
from typing import cast

from ofti.tools import change_queue_service, lint_service, table_render_service
from ofti.tools.cli_tools import knife as knife_ops


def _knife_doctor(args: argparse.Namespace) -> int:
    payload = knife_ops.doctor_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return knife_ops.doctor_exit_code(payload)
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.doctor_table_lines(payload)))
        return knife_ops.doctor_exit_code(payload)
    for line in payload["lines"]:
        print(line)
    if payload["errors"]:
        print("\nErrors:")
        for item in payload["errors"]:
            print(f"- {item}")
    if payload["warnings"]:
        print("\nWarnings:")
        for item in payload["warnings"]:
            print(f"- {item}")
    if not payload["errors"] and not payload["warnings"]:
        print("\nOK: no issues found.")
    return knife_ops.doctor_exit_code(payload)


def _knife_lint(args: argparse.Namespace) -> int:
    payload = lint_service.lint_payload(args.case_dir)
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return lint_service.lint_exit_code(payload)
    print("\n".join(table_render_service.lint_table_lines(payload)))
    return lint_service.lint_exit_code(payload)


def _knife_changes(args: argparse.Namespace) -> int:
    payload = change_queue_service.change_queue_payload(
        args.case_dir,
        write_snapshot=bool(getattr(args, "snapshot", False)),
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("\n".join(table_render_service.change_queue_table_lines(payload)))
    return 0


def _knife_preflight(args: argparse.Namespace) -> int:
    payload = knife_ops.preflight_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.preflight_table_lines(payload)))
        return 0 if payload["ok"] else 1
    print(f"case={payload['case']}")
    for key, value in payload["checks"].items():
        print(f"{key}={'ok' if value else 'missing'}")
    if payload["solver_error"]:
        print(f"solver_error={payload['solver_error']}")
    print(f"ok={payload['ok']}")
    return 0 if payload["ok"] else 1


def _knife_compare(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.compare_payload(
            args.left_case,
            args.right_case,
            flat=bool(getattr(args, "flat", False)),
            files=list(getattr(args, "files", [])),
            raw_hash_only=bool(getattr(args, "raw_hash", False)),
        )
    except TypeError:
        payload = knife_ops.compare_payload(args.left_case, args.right_case)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.compare_table_lines(payload)))
        return 0
    print(f"left_case={payload['left_case']}")
    print(f"right_case={payload['right_case']}")
    print(f"diff_count={payload['diff_count']}")
    if not payload["diffs"]:
        print("No dictionary key differences detected.")
        return 0
    for diff in payload["diffs"]:
        _print_compare_diff(diff, flat=bool(payload.get("flat")))
    return 0


def _print_compare_diff(diff: dict[str, object], *, flat: bool) -> None:
    print(f"\n{diff['rel_path']}")
    print(f"  kind: {diff.get('kind', 'dict')}")
    if diff["error"]:
        print(f"  error: {diff['error']}")
    missing_left = cast("list[str]", diff.get("missing_in_left", []))
    missing_right = cast("list[str]", diff.get("missing_in_right", []))
    if missing_left:
        print(f"  missing_in_left: {', '.join(missing_left)}")
    if missing_right:
        print(f"  missing_in_right: {', '.join(missing_right)}")
    _print_compare_values(diff, flat=flat)
    if diff.get("left_hash") or diff.get("right_hash"):
        print(f"  left_hash={diff.get('left_hash')}")
        print(f"  right_hash={diff.get('right_hash')}")


def _print_compare_values(diff: dict[str, object], *, flat: bool) -> None:
    if flat:
        values = cast("list[str]", diff.get("value_diffs_flat", []))
        for value in values[:40]:
            print(f"  value_diff {value}")
        if len(values) > 40:
            print(f"  value_diff_more={len(values) - 40}")
        return
    values = cast("list[dict[str, object]]", diff.get("value_diffs", []))
    for value in values[:40]:
        print(
            f"  value_diff {value['key']}: left={value['left']} "
            f"right={value['right']}",
        )
    if len(values) > 40:
        print(f"  value_diff_more={len(values) - 40}")


def _knife_copy(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.copy_payload(
            args.case_dir,
            args.destination,
            include_runtime_artifacts=bool(args.with_trash),
            drop_mesh=bool(args.drop_mesh),
        )
    except ValueError as exc:
        print(f"ofti: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"source={payload['source']}")
    print(f"destination={payload['destination']}")
    print(f"include_runtime_artifacts={payload['include_runtime_artifacts']}")
    print(f"drop_mesh={payload['drop_mesh']}")
    print(f"ok={payload['ok']}")
    return 0


def _knife_set(args: argparse.Namespace) -> int:
    value = " ".join(args.value).strip()
    payload = knife_ops.set_entry_payload(args.case_dir, args.file, args.key, value)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1
    print(f"file={payload['file']}")
    print(f"key={payload['key']}")
    print(f"value={payload['value']}")
    print(f"ok={payload['ok']}")
    return 0 if payload["ok"] else 1
