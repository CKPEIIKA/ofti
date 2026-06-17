from __future__ import annotations

import os
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
from ofti.foam.times import latest_time
from ofti.tools import (
    case_source_service,
    case_status_service,
    process_scan_service,
    runtime_control_service,
    watch_service,
)
from ofti.tools import knife_runtime as _runtime
from ofti.tools.case_doctor import build_case_doctor_report
from ofti.tools.job_registry import refresh_jobs, register_job
from ofti.tools.knife_process import (
    _path_within,
    _running_job_pids,
    _scan_proc_solver_processes,
)

# Re-export criteria/ETA/convergence/report helpers so knife_service stays the
# canonical home for the CLI facade and tests. Assignments (not `from` imports)
# keep these from being pruned as "unused" while several have no internal caller.
criteria_eta_details = _runtime.criteria_eta_details
criteria_rows_from_rtc = _runtime.criteria_rows_from_rtc
criteria_satisfaction_eta = _runtime.criteria_satisfaction_eta
criteria_unknown_reason = _runtime.criteria_unknown_reason
criterion_source = _runtime.criterion_source
converge_payload = _runtime.converge_payload
report_markdown = _runtime.report_markdown
select_eta = _runtime.select_eta
stability_payload = _runtime.stability_payload

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
