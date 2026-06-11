from __future__ import annotations

import argparse
import json
from pathlib import Path

from ofti.app.cli_adapters import run as run_cli
from ofti.tools import run_manifest_service as manifest_ops
from ofti.tools import table_render_service
from ofti.tools.cli_tools import run as run_ops


def _knife_receipt_write(args: argparse.Namespace) -> int:
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
    command = run_ops.dry_run_command(cmd)
    manifest_path = manifest_ops.write_case_run_manifest(
        Path(args.case_dir),
        name=display,
        command=command,
        background=False,
        detached=False,
        parallel=parallel,
        mpi=args.mpi,
        sync_subdomains=sync_subdomains,
        prepare_parallel=prepare_parallel,
        clean_processors=clean_processors,
        output=getattr(args, "receipt_file", None),
        record_inputs_copy=bool(getattr(args, "record_inputs_copy", False)),
        solver_name=run_cli._solver_name_for_manifest(cmd, parallel=parallel),
    )
    payload = {
        "case": str(Path(args.case_dir).resolve()),
        "command": command,
        "manifest": str(manifest_path),
        "receipt": str(manifest_path),
        "recorded_inputs_copy": bool(getattr(args, "record_inputs_copy", False)),
        "ok": True,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_list_table_lines(payload)))
        return 0
    print(f"case={payload['case']}")
    print(f"command={payload['command']}")
    print(f"manifest={payload['manifest']}")
    print(f"recorded_inputs_copy={payload['recorded_inputs_copy']}")
    return 0


def _knife_receipt_verify(args: argparse.Namespace) -> int:
    payload = manifest_ops.verify_run_manifest(
        Path(args.receipt),
        case_path=getattr(args, "case_dir", None),
    )
    payload.setdefault("manifest", payload.get("receipt"))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok")) else 1
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.receipt_verify_table_lines(payload)))
        return 0 if bool(payload.get("ok")) else 1
    print(f"manifest={payload['manifest']}")
    print(f"case={payload['case']}")
    print(f"ok={payload['ok']}")
    print(f"expected_tree_hash={payload['expected_tree_hash']}")
    print(f"actual_tree_hash={payload['actual_tree_hash']}")
    print(f"openfoam_version_match={payload['openfoam']['match']}")
    print(f"solver_binary_match={payload['build']['solver']['match']}")
    print(f"linked_libs_match={payload['build']['linked_libs']['match']}")
    if payload["missing_files"]:
        print("missing_files:")
        for path in payload["missing_files"]:
            print(f"- {path}")
    if payload["changed_files"]:
        print("changed_files:")
        for row in payload["changed_files"]:
            print(f"- {row['path']}")
    if payload["extra_files"]:
        print("extra_files:")
        for path in payload["extra_files"]:
            print(f"- {path}")
    return 0 if bool(payload.get("ok")) else 1


def _knife_receipt_restore(args: argparse.Namespace) -> int:
    payload = manifest_ops.restore_run_manifest(
        Path(args.receipt),
        Path(args.destination),
        only=getattr(args, "only", []),
        skip=getattr(args, "skip", []),
    )
    payload.setdefault("manifest", payload.get("receipt"))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if bool(payload.get("ok")) else 1
    print(f"manifest={payload['manifest']}")
    print(f"destination={payload['destination']}")
    print(f"selected_roots={','.join(payload['selected_roots'])}")
    print(f"restored_receipt={payload['restored_receipt']}")
    if payload["restored"]:
        print("restored:")
        for item in payload["restored"]:
            print(f"- {item}")
    return 0 if bool(payload.get("ok")) else 1
