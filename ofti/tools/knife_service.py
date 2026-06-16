from __future__ import annotations

import csv
import os
import re
import shutil
import signal
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from ofti.core.boundary import list_field_files, read_optional, zero_dir
from ofti.core.case_copy import copy_case_directory
from ofti.core.dict_compare import compare_case_dicts
from ofti.core.entry_io import list_subkeys, write_entry
from ofti.core.field_diagnostics import (
    compare_fields_payload as compare_fields_core_payload,
)
from ofti.core.field_diagnostics import (
    field_sanity_payload,
    parse_field_rules,
    write_compare_report,
    write_physical_report,
)
from ofti.core.solver_checks import resolve_solver_name
from ofti.core.solver_status import latest_solver_job, solver_status_text
from ofti.core.times import latest_time
from ofti.foamlib.logs import (
    parse_residuals,
    read_log_text,
)
from ofti.tools import (
    case_source_service,
    case_status_service,
    convergence_service,
    process_scan_service,
    runtime_control_service,
    watch_service,
)
from ofti.tools.case_doctor import build_case_doctor_report
from ofti.tools.job_registry import refresh_jobs, register_job
from ofti.tools.process_scan_service import ProcEntry

_DELTA_T_RE = runtime_control_service.DELTA_T_RE
_END_TIME_RE = runtime_control_service.END_TIME_RE


def doctor_payload(case_dir: Path) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    report = build_case_doctor_report(case_path)
    return {
        "case": str(case_path),
        "lines": report["lines"],
        "errors": report["errors"],
        "warnings": report["warnings"],
    }


def doctor_exit_code(payload: dict[str, Any]) -> int:
    errors = payload.get("errors", [])
    return 1 if errors else 0


def current_payload(case_dir: Path, *, live: bool = False) -> case_status_service.CurrentPayload:
    case_path = case_source_service.require_case_dir(case_dir)
    payload = case_status_service.current_payload(
        case_path,
        resolve_solver_name_fn=resolve_solver_name,
        refresh_jobs_fn=refresh_jobs,
        running_job_pids_fn=_running_job_pids,
        scan_proc_solver_processes_fn=_scan_proc_solver_processes,
        live=live,
    )
    warning = process_scan_service.proc_access_warning()
    case_status_service.attach_process_visibility(cast("dict[str, Any]", payload), warning)
    return payload


def current_scope_payload(
    case_dir: Path,
    *,
    live: bool = False,
    recursive: bool = False,
) -> dict[str, Any]:
    scope_root = case_source_service.require_case_dir(case_dir)
    root_is_case = process_scan_service.is_case_dir(scope_root)
    recursive_effective = recursive or not root_is_case
    if not recursive_effective:
        return dict(current_payload(scope_root, live=live))

    case_paths = _discover_case_dirs(scope_root)
    jobs_all: list[dict[str, Any]] = []
    active_jobs: list[dict[str, Any]] = []
    for case_path in case_paths:
        jobs = refresh_jobs(case_path)
        for job in jobs:
            row = dict(job)
            row["case"] = str(case_path)
            jobs_all.append(row)
            if row.get("status") in {"running", "paused"}:
                active_jobs.append(row)
    tracked_pids = set(_running_job_pids(active_jobs))
    untracked = _scan_proc_solver_processes(
        scope_root,
        None,
        tracked_pids=tracked_pids,
        require_case_target=not live,
    )
    untracked = [
        row
        for row in untracked
        if (case_path := _adopt_case_path(row)) is not None and _path_within(case_path, scope_root)
    ]
    cases_from_untracked = sorted(
        {
            str(case_path)
            for row in untracked
            if (case_path := _adopt_case_path(row)) is not None
        },
    )
    case_rows = sorted({str(path) for path in case_paths} | set(cases_from_untracked))
    untracked_count = case_status_service.untracked_running_count(untracked)
    running_count = len(active_jobs) + untracked_count
    payload = {
        "case": str(scope_root),
        "scope": "tree",
        "recursive": True,
        "proc_access_warning": None,
        "cases_total": len(case_rows),
        "cases": case_rows,
        "solver": None,
        "solver_error": None,
        "jobs": active_jobs,
        "jobs_total": len(jobs_all) + untracked_count,
        "jobs_running": running_count,
        "jobs_tracked_running": len(active_jobs),
        "jobs_registry_running": len(active_jobs),
        "runs": case_status_service.canonical_run_rows(scope_root, active_jobs, untracked),
        "process_visibility": None,
        "untracked_processes": untracked,
    }
    case_status_service.attach_process_visibility(
        payload,
        process_scan_service.proc_access_warning(),
    )
    return payload


def current_live_payload(case_dir: Path) -> case_status_service.CurrentPayload:
    return current_payload(case_dir, live=True)


def adopt_payload(
    case_dir: Path,
    *,
    recursive: bool = False,
    all_untracked: bool = False,
) -> dict[str, Any]:
    scope_root = case_source_service.require_case_dir(case_dir)
    root_is_case = process_scan_service.is_case_dir(scope_root)
    recursive_effective = recursive or all_untracked or not root_is_case
    snapshot = current_scope_payload(
        scope_root,
        live=True,
        recursive=recursive_effective,
    )
    rows_by_case = _adopt_rows_by_case(
        snapshot["untracked_processes"],
        scope_root=scope_root,
        root_is_case=root_is_case,
        recursive=recursive_effective,
    )
    case_paths = set(rows_by_case)
    if root_is_case:
        case_paths.add(scope_root)

    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    adopted: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    jobs_running_before = 0
    for case_path in sorted(case_paths, key=str):
        jobs = refresh_jobs(case_path)
        active_jobs = [job for job in jobs if job.get("status") in {"running", "paused"}]
        jobs_running_before += len(active_jobs)
        tracked_pids = set(_running_job_pids(active_jobs))
        case_rows = rows_by_case.get(case_path, [])
        launcher_pids = {
            int(row["pid"])
            for row in case_rows
            if str(row.get("role")) == "launcher" and int(row.get("pid", 0)) > 0
        }

        for row in case_rows:
            pid = int(row.get("pid", 0) or 0)
            if pid <= 0:
                continue
            role = str(row.get("role", "solver"))
            launcher_pid = _to_positive_int(row.get("launcher_pid"))
            if role == "solver" and launcher_pid is not None and launcher_pid in launcher_pids:
                # The launcher process represents this solver subtree.
                continue
            if pid in tracked_pids:
                skipped.append(
                    {
                        "case": str(case_path),
                        "pid": pid,
                        "reason": "already_tracked",
                    },
                )
                continue
            selected_row = {
                "case": str(case_path),
                "pid": pid,
                "role": role,
                "solver": row.get("solver"),
                "command": str(row.get("command") or ""),
                "launcher_pid": launcher_pid,
                "solver_pids": row.get("solver_pids", []),
                "log_path": row.get("log_path") or row.get("log"),
            }
            selected.append(selected_row)

    for row in selected:
        case_path = Path(str(row["case"]))
        pid = int(row["pid"])
        command = str(row.get("command") or "")
        role = str(row.get("role") or "solver")
        solver_name = str(row.get("solver") or "solver")
        name = solver_name if role == "solver" else f"{solver_name}-launcher"
        solver_pids = [item for item in row.get("solver_pids", []) if isinstance(item, int)]
        log_path = _adopt_log_path(case_path, solver_name)
        try:
            job_id = register_job(
                case_path,
                name,
                pid,
                command,
                log_path,
                kind="solver",
                detached=True,
                extra={
                    "adopted": True,
                    "role": role,
                    "solver_pids": solver_pids,
                    "launcher_pid": pid if role == "launcher" else row.get("launcher_pid"),
                },
            )
        except OSError as exc:
            failed.append(
                {
                    "case": str(case_path),
                    "pid": pid,
                    "error": str(exc),
                },
            )
            continue
        adopted.append(
            {
                "case": str(case_path),
                "id": job_id,
                "pid": pid,
                "name": name,
                "role": role,
                "solver_pids": solver_pids,
                "launcher_pid": pid if role == "launcher" else row.get("launcher_pid"),
                "log": str(log_path),
                "command": command,
            },
        )

    return {
        "case": str(scope_root),
        "scope": "tree" if recursive_effective else "case",
        "recursive": recursive_effective,
        "all_untracked": bool(all_untracked),
        "cases_total": len(case_paths),
        "cases": [str(path) for path in sorted(case_paths, key=str)],
        "selected": len(selected),
        "adopted": adopted,
        "failed": failed,
        "skipped": skipped,
        "jobs_running_before": jobs_running_before,
        "jobs_running_after": jobs_running_before + len(adopted),
    }


def _discover_case_dirs(scope_root: Path) -> list[Path]:
    root = scope_root.resolve()
    cases: set[Path] = set()
    if process_scan_service.is_case_dir(root):
        cases.add(root)

    for dir_path, dir_names, _file_names in os.walk(root):
        path = Path(dir_path)
        _prune_case_walk(dir_names)
        if process_scan_service.is_case_dir(path):
            cases.add(path.resolve())
    return sorted(cases, key=str)


def _prune_case_walk(dir_names: list[str]) -> None:
    pruned = [
        name
        for name in dir_names
        if not (
            name.startswith("processor")
            or name in {".git", ".venv", "__pycache__", "postProcessing", ".mypy_cache"}
        )
    ]
    dir_names[:] = pruned


def _adopt_rows_by_case(
    rows: list[dict[str, Any]],
    *,
    scope_root: Path,
    root_is_case: bool,
    recursive: bool,
) -> dict[Path, list[dict[str, Any]]]:
    by_case: dict[Path, list[dict[str, Any]]] = {}
    for row in rows:
        case_path = _adopt_case_path(row)
        if case_path is None:
            continue
        if root_is_case and not recursive:
            if case_path != scope_root:
                continue
        elif not _path_within(case_path, scope_root):
            continue
        if case_path not in by_case:
            by_case[case_path] = []
        by_case[case_path].append(row)
    return by_case


def _adopt_case_path(row: Mapping[str, Any]) -> Path | None:
    case_raw = str(row.get("case") or "").strip()
    if not case_raw:
        return None
    try:
        return Path(case_raw).expanduser().resolve()
    except OSError:
        return None


def _adopt_log_path(case_path: Path, solver: str | None) -> Path:
    if solver and solver != "unknown":
        candidate = (case_path / f"log.{solver}").resolve()
        if candidate.is_file():
            return candidate
    logs = sorted(
        case_path.glob("log.*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if logs:
        return logs[0].resolve()
    safe = solver if solver and solver != "unknown" else "solver"
    return (case_path / f"log.{safe}").resolve()


def _to_positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def compare_payload(
    left_case: Path,
    right_case: Path,
    *,
    files: list[str] | None = None,
    flat: bool = False,
    raw_hash_only: bool = False,
) -> dict[str, Any]:
    left = case_source_service.require_case_dir(left_case)
    right = case_source_service.require_case_dir(right_case)
    diffs = compare_case_dicts(left, right)
    file_filter = _compare_file_filter(files)
    if file_filter:
        diffs = [diff for diff in diffs if diff.rel_path in file_filter]
    if raw_hash_only:
        diffs = [diff for diff in diffs if diff.kind != "dict"]
    return {
        "left_case": str(left),
        "right_case": str(right),
        "flat": flat,
        "files": sorted(file_filter) if file_filter else [],
        "raw_hash_only": raw_hash_only,
        "diff_count": len(diffs),
        "diffs": [
            {
                "rel_path": diff.rel_path,
                "kind": diff.kind,
                "missing_in_left": diff.missing_in_left,
                "missing_in_right": diff.missing_in_right,
                "value_diffs": [
                    {"key": value.key, "left": value.left, "right": value.right}
                    for value in diff.value_diffs
                ],
                "value_diffs_flat": [
                    f"{value.key}: left={value.left} right={value.right}"
                    for value in diff.value_diffs
                ],
                "left_hash": diff.left_hash,
                "right_hash": diff.right_hash,
                "error": diff.error,
            }
            for diff in diffs
        ],
    }


def physical_payload(
    case_dir: Path,
    *,
    time_name: str = "latest",
    fields: list[str] | None = None,
    rules: list[str] | None = None,
    patch: str | None = None,
    out_dir: Path | None = None,
    report_stem: str = "physical",
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    payload = field_sanity_payload(
        case_path,
        time_name=time_name,
        fields=fields,
        rules=parse_field_rules(rules),
        patch=patch,
    )
    if out_dir is not None:
        payload["outputs"] = write_physical_report(payload, out_dir, stem=report_stem)
    return payload


def compare_fields_payload(
    left_case: Path,
    right_case: Path,
    *,
    time_name: str = "latest",
    reference_time: str | None = None,
    candidate_time: str | None = None,
    fields: list[str] | None = None,
    preset: str | None = None,
    patch: str | None = None,
    out_dir: Path | None = None,
    abs_tol: float = 1e-300,
    rel_tol: float = 1e-12,
) -> dict[str, Any]:
    left = case_source_service.require_case_dir(left_case)
    right = case_source_service.require_case_dir(right_case)
    payload = compare_fields_core_payload(
        left,
        right,
        time_name=time_name,
        reference_time=reference_time,
        candidate_time=candidate_time,
        fields=fields,
        preset=preset,
        patch=patch,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
    )
    if out_dir is not None:
        payload["outputs"] = write_compare_report(payload, out_dir)
    return payload


def copy_payload(
    case_dir: Path,
    destination: Path,
    *,
    include_runtime_artifacts: bool = False,
    drop_mesh: bool = False,
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    dest = copy_case_directory(
        case_path,
        destination,
        include_runtime_artifacts=include_runtime_artifacts,
        drop_mesh=drop_mesh,
        keep_zero_directory=True,
    )
    return {
        "source": str(case_path),
        "destination": str(dest),
        "include_runtime_artifacts": include_runtime_artifacts,
        "drop_mesh": drop_mesh,
        "ok": True,
    }


def initials_payload(case_dir: Path) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    initial_dir = zero_dir(case_path)
    fields = list_field_files(case_path)
    rows: list[dict[str, Any]] = []
    all_patches: set[str] = set()
    for field in fields:
        field_path = initial_dir / field
        patches: dict[str, dict[str, str | None]] = {}
        try:
            patch_names = sorted(set(list_subkeys(field_path, "boundaryField")))
        except Exception:
            patch_names = []
        for patch in patch_names:
            all_patches.add(patch)
            patches[patch] = {
                "type": read_optional(field_path, f"boundaryField.{patch}.type"),
                "value": read_optional(field_path, f"boundaryField.{patch}.value"),
            }
        rows.append(
            {
                "name": field,
                "path": str(field_path),
                "internal_field": read_optional(field_path, "internalField"),
                "boundary": patches,
            },
        )
    return {
        "case": str(case_path),
        "initial_dir": str(initial_dir),
        "field_count": len(rows),
        "patch_count": len(all_patches),
        "fields": rows,
    }


def status_payload(
    case_dir: Path,
    *,
    lightweight: bool = False,
    tail_bytes: int | None = None,
) -> case_status_service.CaseStatusPayload:
    case_path = case_source_service.require_case_dir(case_dir)
    payload = case_status_service.status_payload(
        case_path,
        resolve_solver_name_fn=resolve_solver_name,
        refresh_jobs_fn=refresh_jobs,
        running_job_pids_fn=_running_job_pids,
        scan_proc_solver_processes_fn=_scan_proc_solver_processes,
        runtime_control_snapshot_fn=_runtime_control_snapshot,
        latest_solver_job_fn=latest_solver_job,
        solver_status_text_fn=solver_status_text,
        latest_time_fn=latest_time,
        lightweight=lightweight,
        tail_bytes=tail_bytes,
    )
    warning = process_scan_service.proc_access_warning()
    case_status_service.attach_process_visibility(cast("dict[str, Any]", payload), warning)
    return payload


def criteria_payload(
    case_dir: Path,
    *,
    lightweight: bool = False,
    tail_bytes: int | None = None,
) -> dict[str, Any]:
    status = status_payload(
        case_dir,
        lightweight=lightweight,
        tail_bytes=tail_bytes,
    )
    rtc = status.get("run_time_control", {})
    criteria = criteria_rows_from_rtc(rtc)
    return {
        "case": status["case"],
        "solver": status.get("solver"),
        "solver_error": status.get("solver_error"),
        "criteria_count": len(criteria),
        "criteria": criteria,
        "criteria_start": rtc.get("criteria_start"),
        "end_time": rtc.get("end_time"),
        "passed": rtc.get("passed", 0),
        "failed": rtc.get("failed", 0),
        "unknown": rtc.get("unknown", 0),
        "eta_to_criteria_start": status.get("eta_seconds_to_criteria_start"),
    }


def eta_payload(
    case_dir: Path,
    *,
    mode: str,
    lightweight: bool = False,
    tail_bytes: int | None = None,
) -> dict[str, Any]:
    status = status_payload(
        case_dir,
        lightweight=lightweight,
        tail_bytes=tail_bytes,
    )
    rtc = status.get("run_time_control", {})
    eta_end = status.get("eta_seconds_to_end_time")
    criteria_details = criteria_eta_details(
        rtc.get("criteria", []),
        eta_to_criteria_start=status.get("eta_seconds_to_criteria_start"),
        eta_to_end_time=eta_end,
    )
    selected = select_eta(
        requested_mode=mode,
        criteria_details=criteria_details,
        eta_to_end_time=eta_end,
    )
    return {
        "case": status["case"],
        "mode": mode,
        "eta_mode": selected["mode"],
        "eta_reason": selected["reason"],
        "eta_confidence": selected["confidence"],
        "eta_seconds": selected["eta_seconds"],
        "eta_criteria_seconds": criteria_details["eta_worst_seconds"],
        "eta_criteria_worst_seconds": criteria_details["eta_worst_seconds"],
        "eta_criteria_all_seconds": criteria_details["eta_all_seconds"],
        "eta_criteria_unavailable": criteria_details["unavailable"],
        "eta_end_time_seconds": eta_end,
        "criteria_start": rtc.get("criteria_start"),
        "end_time": rtc.get("end_time"),
        "running": status.get("running"),
    }


def report_payload(
    case_dir: Path,
    *,
    lightweight: bool = False,
    tail_bytes: int | None = None,
) -> dict[str, Any]:
    status = status_payload(
        case_dir,
        lightweight=lightweight,
        tail_bytes=tail_bytes,
    )
    rtc = status.get("run_time_control", {})
    criteria_rows = criteria_rows_from_rtc(rtc)
    eta_criteria = criteria_satisfaction_eta(status.get("run_time_control", {}).get("criteria", []))
    return {
        "case": status["case"],
        "solver": status.get("solver"),
        "running": status.get("running"),
        "log": {
            "path": status.get("log_path"),
            "fresh": status.get("log_fresh"),
        },
        "metrics": {
            "latest_time": status.get("latest_time"),
            "latest_iteration": status.get("latest_iteration"),
            "latest_delta_t": status.get("latest_delta_t"),
            "sec_per_iter": status.get("sec_per_iter"),
        },
        "criteria": {
            "count": len(criteria_rows),
            "passed": rtc.get("passed", 0),
            "failed": rtc.get("failed", 0),
            "unknown": rtc.get("unknown", 0),
            "items": criteria_rows,
        },
        "eta": {
            "criteria_seconds": eta_criteria,
            "end_time_seconds": status.get("eta_seconds_to_end_time"),
            "criteria_start_seconds": status.get("eta_seconds_to_criteria_start"),
        },
    }


def campaign_case_paths(
    case_dir: Path,
    *,
    case_glob: str = "*",
    summary_csv: Path | None = None,
) -> list[Path]:
    root = case_source_service.require_case_dir(case_dir)
    discovered: list[Path] = []
    discovered.extend(_campaign_summary_paths(root, summary_csv))
    if not discovered:
        discovered.extend(_campaign_glob_paths(root, case_glob))
    unique_map: dict[str, Path] = {}
    for path in discovered:
        resolved = path.resolve()
        unique_map[str(resolved)] = resolved
    ordered = [unique_map[key] for key in sorted(unique_map)]
    return [path for path in ordered if process_scan_service.is_case_dir(path)]


def campaign_list_payload(
    case_dir: Path,
    *,
    case_glob: str = "*",
    summary_csv: Path | None = None,
) -> dict[str, Any]:
    root = case_source_service.require_case_dir(case_dir)
    cases = campaign_case_paths(root, case_glob=case_glob, summary_csv=summary_csv)
    return {
        "case": str(root),
        "summary_csv": str(summary_csv.resolve()) if summary_csv is not None else None,
        "glob": case_glob,
        "count": len(cases),
        "cases": [str(path) for path in cases],
    }


def campaign_status_payload(
    case_dir: Path,
    *,
    case_glob: str = "*",
    summary_csv: Path | None = None,
    tail_bytes: int = 256 * 1024,
) -> dict[str, Any]:
    root = case_source_service.require_case_dir(case_dir)
    cases = campaign_case_paths(root, case_glob=case_glob, summary_csv=summary_csv)
    rows = [_campaign_case_status(path, tail_bytes=tail_bytes) for path in cases]
    return {
        "case": str(root),
        "summary_csv": str(summary_csv.resolve()) if summary_csv is not None else None,
        "glob": case_glob,
        "count": len(rows),
        "cases": rows,
    }


def campaign_rank_payload(
    case_dir: Path,
    *,
    by: str = "convergence",
    case_glob: str = "*",
    summary_csv: Path | None = None,
    tail_bytes: int = 256 * 1024,
) -> dict[str, Any]:
    if by != "convergence":
        raise ValueError(f"unsupported campaign rank mode: {by}")
    status = campaign_status_payload(
        case_dir,
        case_glob=case_glob,
        summary_csv=summary_csv,
        tail_bytes=tail_bytes,
    )
    ranked = sorted(
        status["cases"],
        key=_campaign_rank_key,
    )
    return {
        "case": status["case"],
        "summary_csv": status["summary_csv"],
        "glob": case_glob,
        "by": by,
        "count": len(ranked),
        "ranked": ranked,
    }


def campaign_stop_worst_payload(
    case_dir: Path,
    *,
    worst: int,
    case_glob: str = "*",
    summary_csv: Path | None = None,
    signal_name: str = "TERM",
    dry_run: bool = False,
    tail_bytes: int = 256 * 1024,
) -> dict[str, Any]:
    if worst <= 0:
        raise ValueError("worst must be > 0")
    rank = campaign_rank_payload(
        case_dir,
        by="convergence",
        case_glob=case_glob,
        summary_csv=summary_csv,
        tail_bytes=tail_bytes,
    )
    ranked = rank["ranked"]
    selected = ranked[-worst:] if worst < len(ranked) else ranked
    actions: list[dict[str, Any]] = []
    for row in selected:
        case_path = Path(str(row["case"]))
        if dry_run:
            actions.append(
                {
                    "case": str(case_path),
                    "dry_run": True,
                    "selected": 0,
                    "stopped": [],
                    "failed": [],
                },
            )
            continue
        actions.append(
            stop_payload(
                case_path,
                all_jobs=True,
                signal_name=signal_name,
            ),
        )
    return {
        "case": rank["case"],
        "by": "convergence",
        "requested": worst,
        "selected": len(selected),
        "dry_run": dry_run,
        "targets": [str(row["case"]) for row in selected],
        "actions": actions,
    }


def campaign_keep_best_payload(
    case_dir: Path,
    *,
    best: int,
    case_glob: str = "*",
    summary_csv: Path | None = None,
    signal_name: str = "TERM",
    dry_run: bool = False,
    tail_bytes: int = 256 * 1024,
) -> dict[str, Any]:
    if best <= 0:
        raise ValueError("best must be > 0")
    rank = campaign_rank_payload(
        case_dir,
        by="convergence",
        case_glob=case_glob,
        summary_csv=summary_csv,
        tail_bytes=tail_bytes,
    )
    ranked = rank["ranked"]
    if best >= len(ranked):
        targets: list[dict[str, Any]] = []
    else:
        targets = ranked[best:]
    actions: list[dict[str, Any]] = []
    for row in targets:
        case_path = Path(str(row["case"]))
        if dry_run:
            actions.append(
                {
                    "case": str(case_path),
                    "dry_run": True,
                    "selected": 0,
                    "stopped": [],
                    "failed": [],
                },
            )
            continue
        actions.append(
            stop_payload(
                case_path,
                all_jobs=True,
                signal_name=signal_name,
            ),
        )
    return {
        "case": rank["case"],
        "by": "convergence",
        "requested": best,
        "kept": min(best, len(ranked)),
        "stopped": len(targets),
        "dry_run": dry_run,
        "kept_cases": [str(row["case"]) for row in ranked[:best]],
        "targets": [str(row["case"]) for row in targets],
        "actions": actions,
    }


def campaign_compare_payload(
    case_dir: Path,
    *,
    group_by: str = "speed",
    case_glob: str = "*",
    summary_csv: Path | None = None,
) -> dict[str, Any]:
    root = case_source_service.require_case_dir(case_dir)
    cases = campaign_case_paths(root, case_glob=case_glob, summary_csv=summary_csv)
    summary_rows = _summary_rows(summary_csv)
    grouped: dict[str, list[Path]] = {}
    for path in cases:
        key = _campaign_group_value(path, group_by=group_by, summary_rows=summary_rows)
        grouped.setdefault(key, []).append(path)
    comparisons: list[dict[str, Any]] = []
    for key in sorted(grouped):
        group_cases = sorted(grouped[key], key=str)
        if len(group_cases) < 2:
            continue
        baseline = Path(str(group_cases[0]))
        for candidate in group_cases[1:]:
            candidate_path = Path(str(candidate))
            diff = compare_payload(
                baseline,
                candidate_path,
                flat=True,
                files=None,
                raw_hash_only=False,
            )
            comparisons.append(
                {
                    "group": key,
                    "left_case": str(baseline),
                    "right_case": str(candidate_path),
                    "diff_count": diff["diff_count"],
                },
            )
    return {
        "case": str(root),
        "group_by": group_by,
        "summary_csv": str(summary_csv.resolve()) if summary_csv is not None else None,
        "group_count": len(grouped),
        "groups": {
            key: [str(path) for path in sorted(paths, key=str)]
            for key, paths in sorted(grouped.items(), key=lambda item: item[0])
        },
        "comparisons": comparisons,
    }


def stop_payload(
    case_dir: Path,
    *,
    job_id: str | None = None,
    name: str | None = None,
    all_jobs: bool = False,
    signal_name: str = "TERM",
) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    signal_upper = signal_name.strip().upper()
    tracked = watch_service.stop_payload(
        case_path,
        job_id=job_id,
        name=name,
        all_jobs=all_jobs,
        kind="solver",
        signal_name=signal_upper,
    )
    untracked = _stop_untracked_solver_processes(case_path, signal_name=signal_upper)
    stopped = [*tracked.get("stopped", []), *untracked["stopped"]]
    failed = [*tracked.get("failed", []), *untracked["failed"]]
    return {
        "case": str(case_path),
        "signal": signal_upper,
        "selected": int(tracked.get("selected", 0)) + untracked["selected"],
        "stopped": stopped,
        "failed": failed,
        "tracked": tracked,
        "untracked": untracked,
    }


def criteria_rows_from_rtc(rtc: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": row.get("key"),
            "value": row.get("live_value"),
            "target": row.get("value"),
            "tol": row.get("tolerance"),
            "status": row.get("status"),
            "met": row.get("status") == "pass",
            "unmet": row.get("unmet_reason"),
            "reason": criteria_unknown_reason(row),
            "window": {
                "samples": row.get("samples"),
                "delta": row.get("live_delta"),
            },
            "source": criterion_source(str(row.get("key", ""))),
        }
        for row in rtc.get("criteria", [])
    ]


def criteria_unknown_reason(row: dict[str, Any]) -> str | None:
    status = str(row.get("status") or "unknown")
    if status == "pass":
        return None
    unmet = row.get("unmet_reason")
    if row.get("unmet_reason") == "not_enough_samples":
        return f"not enough samples: {row.get('samples') or 0} observed"
    if unmet == "startup":
        return "waiting for criteria start time"
    if unmet == "condition_not_met":
        return "runTimeControl reports conditions not met"
    if row.get("live_value") is None and row.get("live_delta") is None:
        return "no matching runtime samples in log"
    return "trend unavailable from current samples" if row.get("eta_seconds") is None else unmet


def converge_payload(
    source: Path,
    *,
    strict: bool = False,
    shock_drift_limit: float = 0.02,
    drag_band_limit: float = 0.02,
    mass_limit: float = 1e-4,
) -> convergence_service.ConvergencePayload:
    log_path = case_source_service.resolve_log_source(source)
    text = read_log_text(log_path)
    residuals = parse_residuals(text)
    return convergence_service.converge_from_text(
        log_path,
        text,
        residuals=residuals,
        strict=strict,
        shock_drift_limit=shock_drift_limit,
        drag_band_limit=drag_band_limit,
        mass_limit=mass_limit,
    )


def stability_payload(
    source: Path,
    *,
    pattern: str,
    tolerance: float,
    window: int,
    startup_samples: int = 0,
    comparator: str = "le",
) -> convergence_service.StabilityPayload:
    log_path = case_source_service.resolve_log_source(source)
    text = read_log_text(log_path)
    return convergence_service.stability_from_text(
        log_path,
        text,
        pattern=pattern,
        tolerance=tolerance,
        window=window,
        startup_samples=startup_samples,
        comparator=comparator,
    )


def preflight_payload(case_dir: Path) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    control_dict_path = case_path / "system" / "controlDict"
    control_dict_ok = control_dict_path.is_file()
    solver, solver_error = resolve_solver_name(case_path)
    if solver is None and control_dict_ok:
        fallback_solver = _fallback_solver(control_dict_path)
        if fallback_solver:
            solver = fallback_solver
            solver_error = None
    checks = {
        "case_dir": True,
        "system/controlDict": control_dict_ok,
        "solver_entry": solver_error is None and bool(solver),
        "0_or_0.orig": (case_path / "0").is_dir() or (case_path / "0.orig").is_dir(),
        "constant/polyMesh/boundary": (case_path / "constant" / "polyMesh" / "boundary").is_file(),
        "openfoam_env": bool(os.environ.get("WM_PROJECT_DIR") or shutil.which("foamVersion")),
    }
    required_checks = ("system/controlDict", "solver_entry")
    ok = all(checks[name] for name in required_checks)
    return {
        "case": str(case_path),
        "ok": ok,
        "checks": checks,
        "solver": solver,
        "solver_error": solver_error,
    }


def _fallback_solver(control_dict_path: Path) -> str | None:
    try:
        text = control_dict_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line or not line.startswith("application"):
            continue
        parts = line.replace(";", " ").split()
        if len(parts) >= 2:
            return parts[1]
    return None


def report_markdown(payload: dict[str, Any]) -> str:
    metrics = payload.get("metrics", {})
    criteria = payload.get("criteria", {})
    eta = payload.get("eta", {})
    lines = [
        f"# OFTI Report: {payload.get('case')}",
        "",
        "## Status",
        f"- solver: {payload.get('solver')}",
        f"- running: {payload.get('running')}",
        (
            f"- log: {payload.get('log', {}).get('path')} "
            f"(fresh={payload.get('log', {}).get('fresh')})"
        ),
        "",
        "## Key metrics",
        f"- latest_time: {metrics.get('latest_time')}",
        f"- latest_iteration: {metrics.get('latest_iteration')}",
        f"- latest_delta_t: {metrics.get('latest_delta_t')}",
        f"- sec_per_iter: {metrics.get('sec_per_iter')}",
        "",
        "## Criteria",
        (
            f"- count: {criteria.get('count')} (pass={criteria.get('passed')} "
            f"fail={criteria.get('failed')} unknown={criteria.get('unknown')})"
        ),
        "",
        "## ETA",
        f"- criteria_seconds: {eta.get('criteria_seconds')}",
        f"- end_time_seconds: {eta.get('end_time_seconds')}",
        f"- criteria_start_seconds: {eta.get('criteria_start_seconds')}",
    ]
    return "\n".join(lines)


def set_entry_payload(case_dir: Path, rel_file: str, key: str, value: str) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    file_path = (case_path / rel_file).resolve()
    if not file_path.is_file():
        raise ValueError(f"dictionary not found: {file_path}")
    ok = write_entry(file_path, key, value)
    return {
        "case": str(case_path),
        "file": str(file_path),
        "key": key,
        "value": value,
        "ok": bool(ok),
    }


def _compare_file_filter(files: list[str] | None) -> set[str]:
    if not files:
        return set()
    selected: set[str] = set()
    for item in files:
        for token in str(item).split(","):
            cleaned = token.strip().replace("\\", "/")
            if cleaned:
                selected.add(cleaned)
    return selected


def criterion_source(key: str) -> str:
    if key.startswith("functions."):
        return "runTimeControl"
    return "controlDict"


def criteria_satisfaction_eta(criteria: list[dict[str, Any]]) -> float | None:
    if not criteria:
        return None
    pending: list[dict[str, Any]] = [row for row in criteria if str(row.get("status")) != "pass"]
    if not pending:
        return 0.0
    eta_values: list[float] = []
    for row in pending:
        value = row.get("eta_seconds")
        if isinstance(value, (int, float)):
            eta_values.append(float(value))
    if not eta_values or len(eta_values) < len(pending):
        return None
    return max(eta_values)


def criteria_eta_details(
    criteria: list[dict[str, Any]],
    *,
    eta_to_criteria_start: float | None,
    eta_to_end_time: float | None,
) -> dict[str, Any]:
    pending: list[dict[str, Any]] = [row for row in criteria if str(row.get("status")) != "pass"]
    if not pending:
        return {
            "eta_worst_seconds": 0.0,
            "eta_all_seconds": 0.0,
            "confidence": 1.0,
            "reason": "criteria_already_met",
            "unavailable": [],
        }
    eta_rows: list[float] = []
    unavailable: list[dict[str, str]] = []
    for row in pending:
        eta_value = row.get("eta_seconds")
        name = str(row.get("key", "criterion"))
        reason = str(row.get("unmet_reason") or "")
        if isinstance(eta_value, (int, float)):
            eta_rows.append(float(eta_value))
            continue
        unavailable.append(
            {
                "name": name,
                "reason": reason or "eta_not_available",
            },
        )
    if eta_rows and not unavailable:
        return {
            "eta_worst_seconds": max(eta_rows),
            "eta_all_seconds": max(eta_rows),
            "confidence": 0.9,
            "reason": "criteria_trend",
            "unavailable": [],
        }
    if eta_to_criteria_start is not None and eta_to_criteria_start > 0:
        return {
            "eta_worst_seconds": eta_to_criteria_start,
            "eta_all_seconds": None,
            "confidence": 0.5,
            "reason": "criteria_start_window",
            "unavailable": unavailable,
        }
    fallback_reason = unavailable[0]["reason"] if unavailable else "criteria_eta_missing"
    if eta_to_end_time is not None:
        return {
            "eta_worst_seconds": None,
            "eta_all_seconds": None,
            "confidence": 0.3,
            "reason": fallback_reason,
            "unavailable": unavailable,
        }
    return {
        "eta_worst_seconds": None,
        "eta_all_seconds": None,
        "confidence": 0.0,
        "reason": fallback_reason,
        "unavailable": unavailable,
    }


def select_eta(
    *,
    requested_mode: str,
    criteria_details: dict[str, Any],
    eta_to_end_time: float | None,
) -> dict[str, Any]:
    if requested_mode == "endtime":
        if eta_to_end_time is None:
            return {
                "eta_seconds": None,
                "mode": "unavailable",
                "reason": "end_time_eta_unavailable",
                "confidence": 0.0,
            }
        return {
            "eta_seconds": eta_to_end_time,
            "mode": "end_time",
            "reason": "end_time_trend",
            "confidence": 0.8,
        }
    eta_worst = criteria_details.get("eta_worst_seconds")
    reason = str(criteria_details.get("reason") or "")
    confidence = float(criteria_details.get("confidence") or 0.0)
    if isinstance(eta_worst, (int, float)):
        if reason == "criteria_start_window":
            return {
                "eta_seconds": float(eta_worst),
                "mode": "criteria_start",
                "reason": reason,
                "confidence": confidence,
            }
        return {
            "eta_seconds": float(eta_worst),
            "mode": "criteria",
            "reason": reason or "criteria_trend",
            "confidence": confidence,
        }
    if eta_to_end_time is not None:
        return {
            "eta_seconds": eta_to_end_time,
            "mode": "end_time",
            "reason": reason or "criteria_unavailable",
            "confidence": min(confidence, 0.4),
        }
    return {
        "eta_seconds": None,
        "mode": "unavailable",
        "reason": reason or "criteria_unavailable",
        "confidence": 0.0,
    }


def _stop_untracked_solver_processes(case_path: Path, *, signal_name: str) -> dict[str, Any]:
    if not process_scan_service.is_case_dir(case_path):
        return {
            "case": str(case_path),
            "selected": 0,
            "stopped": [],
            "failed": [],
            "reason": "case_dir_is_not_openfoam_case",
        }
    tracked_jobs = refresh_jobs(case_path)
    active_jobs = [job for job in tracked_jobs if job.get("status") in {"running", "paused"}]
    tracked_pids = set(_running_job_pids(active_jobs))
    rows = process_scan_service.scan_proc_solver_processes(
        case_path,
        None,
        tracked_pids=tracked_pids,
        include_tracked=False,
        require_case_target=True,
    )
    case_str = str(case_path.resolve())
    selected_rows = [row for row in rows if str(row.get("case") or "") == case_str]
    if not selected_rows:
        return {
            "case": case_str,
            "selected": 0,
            "stopped": [],
            "failed": [],
            "reason": "no_untracked_solver_processes",
        }
    launchers = sorted(
        {
            int(row["pid"])
            for row in selected_rows
            if str(row.get("role")) == "launcher" and int(row.get("pid", 0)) > 0
        },
    )
    solver_rows = [
        row
        for row in selected_rows
        if str(row.get("role")) == "solver" and int(row.get("pid", 0)) > 0
    ]
    solver_pids = sorted({int(row["pid"]) for row in solver_rows})
    if launchers:
        launcher_process_groups = {
            pid: _process_group_if_leader(pid)
            for pid in launchers
        }
        safe_group_launchers = {
            pid
            for pid, pgid in launcher_process_groups.items()
            if pgid == pid
        }
        solver_launcher: dict[int, int | None] = {
            int(row["pid"]): (
                launcher_pid if isinstance((launcher_pid := row.get("launcher_pid")), int) else None
            )
            for row in solver_rows
        }
        # Avoid double-signaling workers only when a launcher group can stop them.
        solver_pids = [
            pid
            for pid in solver_pids
            if solver_launcher.get(pid) not in safe_group_launchers
        ]
    else:
        launcher_process_groups = {}
    signal_code = _signal_number(signal_name)
    stopped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for row in selected_rows:
        pid = int(row.get("pid", 0) or 0)
        role = str(row.get("role") or "solver")
        should_stop = pid in launchers or pid in solver_pids
        if not should_stop:
            continue
        method = "process"
        pgid: int | None = None
        try:
            if role == "launcher" and launcher_process_groups.get(pid) == pid:
                os.killpg(pid, signal_code)
                method = "process_group"
                pgid = pid
            else:
                os.kill(pid, signal_code)
        except OSError as exc:
            failed.append(
                {
                    "id": None,
                    "pid": pid,
                    "name": f"untracked-{role}",
                    "kind": "untracked",
                    "role": role,
                    "case": case_str,
                    "error": str(exc),
                },
            )
            continue
        stopped_row = {
            "id": None,
            "pid": pid,
            "name": f"untracked-{role}",
            "kind": "untracked",
            "role": role,
            "case": case_str,
            "launcher_pid": row.get("launcher_pid"),
            "solver_pids": row.get("solver_pids", []),
            "command": row.get("command"),
            "method": method,
        }
        if pgid is not None:
            stopped_row["pgid"] = pgid
        stopped.append(stopped_row)
    return {
        "case": case_str,
        "selected": len(stopped) + len(failed),
        "stopped": stopped,
        "failed": failed,
        "launcher_pids": launchers,
        "solver_pids": solver_pids,
    }


def _process_group_if_leader(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def _signal_number(name: str) -> int:
    attr = f"SIG{name.strip().upper()}"
    value = getattr(signal, attr, None)
    if isinstance(value, int):
        return value
    return signal.SIGTERM


def _campaign_glob_paths(root: Path, case_glob: str) -> list[Path]:
    candidates: list[Path] = []
    pattern = case_glob.strip() or "*"
    for path in root.glob(pattern):
        if path.is_dir():
            candidates.append(path.resolve())
    return candidates


def _campaign_summary_paths(root: Path, summary_csv: Path | None) -> list[Path]:
    if summary_csv is None:
        return []
    rows = _summary_rows(summary_csv)
    candidates: list[Path] = []
    for row in rows:
        raw = (
            row.get("case")
            or row.get("case_dir")
            or row.get("path")
            or row.get("dir")
            or row.get("case_path")
            or ""
        ).strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        candidates.append(candidate.resolve())
    return candidates


def _summary_rows(summary_csv: Path | None) -> list[dict[str, str]]:
    if summary_csv is None:
        return []
    try:
        with summary_csv.open("r", encoding="utf-8", errors="ignore") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]
    except OSError:
        return []


def _campaign_case_status(case_path: Path, *, tail_bytes: int) -> dict[str, Any]:
    payload = status_payload(
        case_path,
        lightweight=True,
        tail_bytes=tail_bytes,
    )
    rtc = payload.get("run_time_control", {})
    criteria = rtc.get("criteria", [])
    met = int(rtc.get("passed", 0))
    total = len(criteria)
    worst_ratio = _campaign_worst_ratio(criteria)
    criteria_score = (met / total) if total > 0 else 0.0
    return {
        "case": str(case_path),
        "running": bool(payload.get("running")),
        "latest_time": payload.get("latest_time"),
        "latest_iteration": payload.get("latest_iteration"),
        "latest_delta_t": payload.get("latest_delta_t"),
        "sec_per_iter": payload.get("sec_per_iter"),
        "jobs_running": payload.get("jobs_running", 0),
        "criteria_met": met,
        "criteria_total": total,
        "criteria_score": criteria_score,
        "criteria_worst_ratio": worst_ratio,
        "eta_seconds": criteria_satisfaction_eta(criteria),
    }


def _campaign_worst_ratio(criteria: list[dict[str, Any]]) -> float | None:
    ratios: list[float] = []
    for row in criteria:
        tolerance = row.get("tolerance")
        if not isinstance(tolerance, (int, float)):
            continue
        tol = float(tolerance)
        if tol == 0:
            continue
        measured = row.get("live_delta")
        if not isinstance(measured, (int, float)):
            measured = row.get("live_value")
        if not isinstance(measured, (int, float)):
            continue
        ratios.append(abs(float(measured)) / abs(tol))
    if not ratios:
        return None
    return max(ratios)


def _campaign_rank_key(row: dict[str, Any]) -> tuple[float, float, float, str]:
    score = float(row.get("criteria_score") or 0.0)
    worst_ratio = row.get("criteria_worst_ratio")
    ratio_key = float(worst_ratio) if isinstance(worst_ratio, (int, float)) else float("inf")
    latest_time_value = row.get("latest_time")
    latest_key = float(latest_time_value) if isinstance(latest_time_value, (int, float)) else -1.0
    return (-score, ratio_key, -latest_key, str(row.get("case")))


def _campaign_group_value(
    case_path: Path,
    *,
    group_by: str,
    summary_rows: list[dict[str, str]],
) -> str:
    if group_by != "speed":
        return "all"
    summary = _summary_row_for_case(case_path, summary_rows)
    for key in ("speed", "mach", "velocity"):
        value = str(summary.get(key, "")).strip() if summary else ""
        if value:
            return value
    name = case_path.name
    match = re.search(r"(\d+(?:\.\d+)?(?:[eE][-+]?\d+)?[A-Za-z]?)", name)
    if match is None:
        return "unknown"
    return match.group(1)


def _summary_row_for_case(
    case_path: Path,
    rows: list[dict[str, str]],
) -> dict[str, str] | None:
    full = str(case_path.resolve())
    name = case_path.name
    for row in rows:
        values = {
            str(row.get("case", "")),
            str(row.get("case_dir", "")),
            str(row.get("path", "")),
            str(row.get("dir", "")),
            str(row.get("case_path", "")),
            str(row.get("name", "")),
        }
        if full in values or name in values:
            return row
    return None


def _running_job_pids(jobs: list[dict[str, Any]]) -> list[int]:
    return process_scan_service.running_job_pids(jobs)


def _scan_proc_solver_processes(
    case_path: Path,
    solver: str | None,
    *,
    tracked_pids: set[int],
    proc_root: Path = Path("/proc"),
    include_tracked: bool = False,
    require_case_target: bool = True,
) -> list[process_scan_service.ProcRow]:
    return process_scan_service.scan_proc_solver_processes(
        case_path,
        solver,
        tracked_pids=tracked_pids,
        proc_root=proc_root,
        include_tracked=include_tracked,
        require_case_target=require_case_target,
    )


def _proc_table(proc_root: Path) -> dict[int, ProcEntry]:
    return process_scan_service.proc_table(proc_root)


def _launcher_pids_for_case(
    table: dict[int, ProcEntry],
    solver: str | None,
    case_path: Path,
) -> set[int]:
    return process_scan_service.launcher_pids_for_case(table, solver, case_path)


def _launcher_has_solver_descendant(
    pid: int,
    table: dict[int, ProcEntry],
    solver: str | None,
) -> bool:
    return process_scan_service.launcher_has_solver_descendant(pid, table, solver)


def _has_ancestor(pid: int, ancestors: set[int], table: dict[int, ProcEntry]) -> bool:
    return process_scan_service.has_ancestor(pid, ancestors, table)


def _read_proc_args(proc_dir: Path) -> list[str]:
    return process_scan_service.read_proc_args(proc_dir)


def _read_proc_ppid(proc_dir: Path) -> int:
    return process_scan_service.read_proc_ppid(proc_dir)


def _process_role(args: list[str], solver: str | None) -> str | None:
    return process_scan_service.process_role(args, solver)


def _args_match_solver(args: list[str], solver: str) -> bool:
    return process_scan_service.args_match_solver(args, solver)


def _token_matches_solver(text: str, solver: str) -> bool:
    return process_scan_service.token_matches_solver(text, solver)


def _targets_case(proc_dir: Path, args: list[str], case_path: Path) -> bool:
    return process_scan_service.targets_case(proc_dir, args, case_path)


def _entry_targets_case(entry: ProcEntry, case_path: Path) -> bool:
    return process_scan_service.entry_targets_case(entry, case_path)


def _proc_cwd(proc_dir: Path) -> Path | None:
    return process_scan_service.proc_cwd(proc_dir)


def _launcher_descendant_targets_case(
    pid: int,
    table: dict[int, ProcEntry],
    case_path: Path,
) -> bool:
    return process_scan_service.launcher_descendant_targets_case(pid, table, case_path)


def _path_within(path: Path, root: Path) -> bool:
    return process_scan_service.path_within(path, root)


def _looks_like_solver_args(args: list[str]) -> bool:
    return process_scan_service.looks_like_solver_args(args)


def _guess_solver_from_args(args: list[str]) -> str:
    return process_scan_service.guess_solver_from_args(args)


def _runtime_control_snapshot(
    case_path: Path,
    solver: str | None,
    *,
    lightweight: bool = False,
    max_log_bytes: int | None = None,
) -> runtime_control_service.RuntimeControlSnapshot:
    log_path_hint = _live_stdout_log_path(case_path, solver)
    try:
        return runtime_control_service.runtime_control_snapshot(
            case_path,
            solver,
            resolve_log_source_fn=case_source_service.resolve_log_source,
            log_path_hint=log_path_hint,
            lightweight=lightweight,
            max_log_bytes=max_log_bytes,
        )
    except TypeError:
        return runtime_control_service.runtime_control_snapshot(
            case_path,
            solver,
            resolve_log_source_fn=case_source_service.resolve_log_source,
        )


def _resolve_solver_log(case_path: Path, solver: str | None) -> Path | None:
    return runtime_control_service.resolve_solver_log(
        case_path,
        solver,
        resolve_log_source_fn=case_source_service.resolve_log_source,
        log_path_hint=_live_stdout_log_path(case_path, solver),
    )


def _live_stdout_log_path(case_path: Path, solver: str | None) -> Path | None:
    try:
        rows = process_scan_service.scan_proc_solver_processes(
            case_path,
            solver,
            tracked_pids=set(),
            include_tracked=True,
            require_case_target=True,
        )
    except OSError:
        return None
    for role in ("launcher", "solver"):
        for row in rows:
            if str(row.get("role")) != role:
                continue
            pid = int(row.get("pid", 0) or 0)
            if pid <= 0:
                continue
            fd1 = Path("/proc") / str(pid) / "fd" / "1"
            try:
                candidate = fd1.resolve()
            except OSError:
                continue
            if candidate.is_file():
                return candidate
    return None
