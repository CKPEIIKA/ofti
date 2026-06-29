from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from ofti.app.cli_adapters.common import solver_name_for_manifest
from ofti.app.cli_help import (
    _EASY_ON_CPU_MIN_POLL_INTERVAL,
    _EASY_ON_CPU_TAIL_BYTES,
    emit_json,
)
from ofti.core import run_manifest as manifest_ops
from ofti.core.field_diagnostics import split_field_list
from ofti.plugins import discover_plugins
from ofti.tools import status_render_service, table_render_service
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import run as run_ops


def _knife_doctor(args: argparse.Namespace) -> int:
    payload = knife_ops.doctor_payload(args.case_dir)
    if args.json:
        emit_json(payload, args)
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

def _knife_preflight(args: argparse.Namespace) -> int:
    payload = knife_ops.preflight_payload(args.case_dir)
    if args.json:
        emit_json(payload, args)
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
        emit_json(payload, args)
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


def _knife_physical(args: argparse.Namespace) -> int:
    fields = split_field_list(list(getattr(args, "fields", []))) or []
    rules = list(getattr(args, "field_rules", []))
    profile_name = getattr(args, "profile", None)
    if profile_name:
        registry = discover_plugins()
        profile = registry.physical_profiles.get(str(profile_name))
        if profile is None:
            available = ", ".join(sorted(registry.physical_profiles)) or "none"
            print(
                f"ofti: physical profile '{profile_name}' is not available; "
                f"install a plugin that provides it (available: {available})",
                file=sys.stderr,
            )
            return 2
        profile_fields = [str(item) for item in profile.fields(args.case_dir)]
        fields = _unique_cli_items([*fields, *profile_fields])
        rules.extend(str(item) for item in profile.rules(args.case_dir))
    payload = knife_ops.physical_payload(
        args.case_dir,
        time_name=str(getattr(args, "time", "latest")),
        fields=fields or None,
        rules=rules,
        patch=getattr(args, "patch", None),
        out_dir=getattr(args, "out", None),
        report_stem="physical",
    )
    if profile_name:
        payload["profile"] = str(profile_name)
        _merge_profile_diagnostics(payload, profile, args)
    return _print_physical_payload(payload, args)


def _merge_profile_diagnostics(
    payload: dict[str, object],
    profile: object,
    args: argparse.Namespace,
) -> None:
    diagnostics_fn = getattr(profile, "diagnostics", None)
    if not callable(diagnostics_fn):
        return
    try:
        diagnostics = diagnostics_fn(args.case_dir, time_name=str(getattr(args, "time", "latest")))
    except (ValueError, OSError):
        return
    if not isinstance(diagnostics, dict):
        return
    extra = [item for item in diagnostics.get("violations", []) if isinstance(item, dict)]
    payload["diagnostics"] = {
        key: value for key, value in diagnostics.items() if key != "violations"
    }
    if extra:
        violations = list(cast("list[object]", payload.get("violations", [])))
        violations.extend(extra)
        payload["violations"] = violations
    payload["physical_ok"] = not payload.get("violations") and not payload.get("hard_errors")


def _unique_cli_items(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _print_physical_payload(payload: dict[str, object], args: argparse.Namespace) -> int:
    if args.json:
        emit_json(payload, args)
        return _physical_exit_code(payload, fail_on_bad=bool(getattr(args, "fail_on_bad", False)))
    print(f"case={payload['case']}")
    print(f"time={payload['time']} fields={payload['field_count']}")
    print(f"ok={payload['ok']} physical_ok={payload['physical_ok']}")
    if payload.get("outputs"):
        print(f"outputs={payload['outputs']}")
    for row in cast("list[dict[str, object]]", payload["fields"]):
        if not row.get("ok"):
            print(f"- {row['field']}: error={row.get('error')}")
            continue
        print(
            f"- {row['field']}: kind={row.get('kind')} count={row.get('count')} "
            f"min={row.get('min')} max={row.get('max')} "
            f"neg={row.get('negative_count')} nonfinite={row.get('nonfinite_count')}",
        )
    for item in cast("list[dict[str, object]]", payload.get("violations", [])):
        print(f"violation: {item}")
    for item in cast("list[str]", payload.get("hard_errors", [])):
        print(f"hard_error: {item}")
    _print_physical_diagnostics(payload)
    return _physical_exit_code(payload, fail_on_bad=bool(getattr(args, "fail_on_bad", False)))


def _print_physical_diagnostics(payload: dict[str, object]) -> None:
    raw = payload.get("diagnostics")
    if not isinstance(raw, dict):
        return
    diagnostics = cast("dict[str, Any]", raw)
    species_sum = diagnostics.get("species_sum")
    if isinstance(species_sum, dict):
        summary = cast("dict[str, Any]", species_sum)
        if summary.get("checked"):
            print(f"species_sum: max_abs_deviation={summary.get('max_abs_deviation')}")
    two_temperature = diagnostics.get("two_temperature")
    if isinstance(two_temperature, dict):
        ratio = cast("dict[str, Any]", two_temperature)
        if ratio.get("checked"):
            print(
                f"two_temperature: ok={ratio.get('ok')} "
                f"ratio_min={ratio.get('ratio_min')} "
                f"ratio_max={ratio.get('ratio_max')}",
            )


def _physical_exit_code(payload: dict[str, object], *, fail_on_bad: bool) -> int:
    if not bool(payload.get("ok", False)):
        return 1
    if fail_on_bad and not bool(payload.get("physical_ok", False)):
        return 1
    return 0


def _knife_compare_fields(args: argparse.Namespace) -> int:
    left_case = getattr(args, "reference", None) or getattr(args, "left_case", None)
    right_case = getattr(args, "candidate", None) or getattr(args, "right_case", None)
    if left_case is None or right_case is None:
        print(
            "compare-fields requires left/right cases or --reference/--candidate",
            file=sys.stderr,
        )
        return 2
    payload = knife_ops.compare_fields_payload(
        left_case,
        right_case,
        time_name=str(getattr(args, "time", "latest")),
        reference_time=getattr(args, "reference_time", None),
        candidate_time=getattr(args, "candidate_time", None),
        fields=split_field_list(list(getattr(args, "fields", []))),
        preset=getattr(args, "preset", None),
        patch=getattr(args, "patch", None),
        out_dir=getattr(args, "out", None),
        abs_tol=float(getattr(args, "abs_tol", 1e-300)),
        rel_tol=float(getattr(args, "rel_tol", 1e-12)),
    )
    if args.json:
        emit_json(payload, args)
        return 0 if bool(payload.get("ok", False)) else 1
    print(f"left_case={payload['left_case']}")
    print(f"right_case={payload['right_case']}")
    print(f"time={payload['time']} fields={payload['field_count']} same={payload['same']}")
    if payload.get("outputs"):
        print(f"outputs={payload['outputs']}")
    for row in cast("list[dict[str, object]]", payload["fields"]):
        if not row.get("ok"):
            print(f"- {row['field']}: error={row.get('error')}")
            continue
        print(
            f"- {row['field']}: kind={row.get('kind')} count={row.get('count')} "
            f"maxAbs={row.get('abs_linf')} relL2={row.get('rel_l2')} "
            f"relLinfSig={row.get('rel_linf_significant')} "
            f"nonfinite={row.get('nonfinite_pairs')}",
        )
    for item in cast("list[str]", payload.get("errors", [])):
        print(f"error: {item}")
    return 0 if bool(payload.get("ok", False)) else 1


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
        emit_json(payload, args)
        return 0
    print(f"source={payload['source']}")
    print(f"destination={payload['destination']}")
    print(f"include_runtime_artifacts={payload['include_runtime_artifacts']}")
    print(f"drop_mesh={payload['drop_mesh']}")
    print(f"ok={payload['ok']}")
    return 0

def _knife_manifest_write(args: argparse.Namespace) -> int:
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
        output=getattr(args, "manifest_file", None),
        record_inputs_copy=bool(getattr(args, "record_inputs_copy", False)),
        solver_name=solver_name_for_manifest(cmd, parallel=parallel),
    )
    payload = {
        "case": str(Path(args.case_dir).resolve()),
        "command": command,
        "manifest": str(manifest_path),
        "recorded_inputs_copy": bool(getattr(args, "record_inputs_copy", False)),
        "ok": True,
    }
    if args.json:
        emit_json(payload, args)
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.campaign_list_table_lines(payload)))
        return 0
    print(f"case={payload['case']}")
    print(f"command={payload['command']}")
    print(f"manifest={payload['manifest']}")
    print(f"recorded_inputs_copy={payload['recorded_inputs_copy']}")
    return 0

def _knife_manifest_verify(args: argparse.Namespace) -> int:
    payload = manifest_ops.verify_run_manifest(
        Path(args.manifest),
        case_path=getattr(args, "case_dir", None),
    )
    if args.json:
        emit_json(payload, args)
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

def _knife_manifest_restore(args: argparse.Namespace) -> int:
    payload = manifest_ops.restore_run_manifest(
        Path(args.manifest),
        Path(args.destination),
        only=getattr(args, "only", []),
        skip=getattr(args, "skip", []),
    )
    if args.json:
        emit_json(payload, args)
        return 0 if bool(payload.get("ok")) else 1
    print(f"manifest={payload['manifest']}")
    print(f"destination={payload['destination']}")
    print(f"selected_roots={','.join(payload['selected_roots'])}")
    print(f"restored_manifest={payload['restored_manifest']}")
    if payload["restored"]:
        print("restored:")
        for item in payload["restored"]:
            print(f"- {item}")
    return 0 if bool(payload.get("ok")) else 1

def _knife_initials(args: argparse.Namespace) -> int:
    payload = knife_ops.initials_payload(args.case_dir)
    if args.json:
        emit_json(payload, args)
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

def _knife_use_lightweight_mode(args: argparse.Namespace) -> bool:
    return not bool(getattr(args, "full", False))

def tail_bytes_with_cpu_mode(args: argparse.Namespace) -> int | None:
    explicit = getattr(args, "tail_bytes", None)
    if explicit is not None:
        return int(explicit)
    if bool(getattr(args, "easy_on_cpu", False)):
        return _EASY_ON_CPU_TAIL_BYTES
    return None

def interval_with_cpu_mode(args: argparse.Namespace, interval: float) -> float:
    value = float(interval)
    if value <= 0:
        value = 0.25
    if bool(getattr(args, "easy_on_cpu", False)):
        value = max(value, _EASY_ON_CPU_MIN_POLL_INTERVAL)
    return value

def _knife_status(args: argparse.Namespace) -> int:
    try:
        payload = knife_ops.status_payload(
            args.case_dir,
            lightweight=_knife_use_lightweight_mode(args),
            tail_bytes=tail_bytes_with_cpu_mode(args),
        )
    except TypeError:
        payload = knife_ops.status_payload(args.case_dir)
    if args.json:
        emit_json(payload, args)
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
        emit_json(payload, args)
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.current_table_lines(payload)))
        return 0
    _print_knife_current(payload)
    return 0

def _knife_current_payload(args: argparse.Namespace) -> Mapping[str, object]:
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

def _print_knife_current(payload: Mapping[str, object]) -> None:
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
    visibility = _object_mapping(payload.get("process_visibility"))
    if visibility.get("message"):
        print(f"process_visibility={visibility['message']}")
    runs = _object_sequence(payload.get("runs"))
    if runs:
        _print_current_runs(runs)
    elif not payload["jobs"]:
        print("No tracked running jobs.")
    else:
        _print_current_jobs(_object_sequence(payload.get("jobs")))
    _print_current_untracked(_object_sequence(payload.get("untracked_processes")))

def _print_current_runs(runs: Sequence[object]) -> None:
    print("runs:")
    for run_obj in runs:
        run = cast("dict[str, object]", run_obj)
        print(
            f"- {run.get('name', 'run')} pid={run.get('pid', '?')} "
            f"source={run.get('source')} status={run.get('status', 'unknown')} "
            f"launcher_pid={run.get('launcher_pid')} solvers={run.get('solver_pids', [])}",
        )

def _print_current_jobs(jobs: Sequence[object]) -> None:
    print("tracked_jobs:")
    for job_obj in jobs:
        job = cast("dict[str, object]", job_obj)
        print(
            f"- {job.get('name', 'job')} pid={job.get('pid', '?')} "
            f"status={job.get('status', 'unknown')}",
        )

def _print_current_untracked(processes: Sequence[object]) -> None:
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
) -> Mapping[str, object]:
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
        emit_json(payload, args)
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
    adopted = _object_sequence(payload.get("adopted"))
    skipped = _object_sequence(payload.get("skipped"))
    failed = _object_sequence(payload.get("failed"))
    print(f"adopted={len(adopted)}")
    if adopted:
        print("adopted_rows:")
        for row_obj in adopted:
            row = _object_mapping(row_obj)
            print(
                f"- id={row.get('id')} pid={row.get('pid')} "
                f"role={row.get('role')} name={row.get('name')} case={row.get('case')}",
            )
    if skipped:
        print("skipped:")
        for row_obj in skipped:
            row = _object_mapping(row_obj)
            print(
                f"- pid={row.get('pid')} reason={row.get('reason')} case={row.get('case')}",
            )
    if failed:
        print("failed:")
        for row_obj in failed:
            row = _object_mapping(row_obj)
            print(
                f"- pid={row.get('pid')} error={row.get('error')} case={row.get('case')}",
            )


def _object_sequence(value: object) -> list[object]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _object_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}

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
        emit_json(payload, args)
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
        emit_json(payload, args)
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
        emit_json(payload, args)
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
        lightweight=_knife_use_lightweight_mode(args),
        tail_bytes=tail_bytes_with_cpu_mode(args),
    )
    if args.json:
        emit_json(payload, args)
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
        lightweight=_knife_use_lightweight_mode(args),
        tail_bytes=tail_bytes_with_cpu_mode(args),
    )
    if args.json:
        emit_json(payload, args)
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
        lightweight=_knife_use_lightweight_mode(args),
        tail_bytes=tail_bytes_with_cpu_mode(args),
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload, args)
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.report_table_lines(payload)))
        return 0
    if fmt == "md":
        print(knife_ops.report_markdown(payload))
        return 0
    emit_json(payload, args)
    return 0

def _knife_campaign_list(args: argparse.Namespace) -> int:
    payload = knife_ops.campaign_list_payload(
        args.case_dir,
        case_glob=str(getattr(args, "glob", "*")),
        summary_csv=getattr(args, "summary_csv", None),
    )
    if args.json:
        emit_json(payload, args)
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
        emit_json(payload, args)
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
        emit_json(payload, args)
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
        emit_json(payload, args)
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
        emit_json(payload, args)
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
        emit_json(payload, args)
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

def _knife_set(args: argparse.Namespace) -> int:
    value = " ".join(args.value).strip()
    payload = knife_ops.set_entry_payload(args.case_dir, args.file, args.key, value)
    if args.json:
        emit_json(payload, args)
        return 0 if payload["ok"] else 1
    print(f"file={payload['file']}")
    print(f"key={payload['key']}")
    print(f"value={payload['value']}")
    print(f"ok={payload['ok']}")
    return 0 if payload["ok"] else 1
