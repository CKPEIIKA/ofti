from __future__ import annotations

import csv
import os
import re
import shutil
import signal
from pathlib import Path
from typing import Any

from ofti.core.boundary import list_field_files, read_optional, zero_dir
from ofti.core.case_copy import copy_case_directory
from ofti.core.dict_compare import compare_case_dicts
from ofti.core.entry_io import list_subkeys, write_entry
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
    return case_status_service.current_payload(
        case_path,
        resolve_solver_name_fn=resolve_solver_name,
        refresh_jobs_fn=refresh_jobs,
        running_job_pids_fn=_running_job_pids,
        scan_proc_solver_processes_fn=_scan_proc_solver_processes,
        live=live,
    )


def current_live_payload(case_dir: Path) -> case_status_service.CurrentPayload:
    return current_payload(case_dir, live=True)


def adopt_payload(case_dir: Path) -> dict[str, Any]:
    case_path = case_source_service.require_case_dir(case_dir)
    snapshot = current_payload(case_path, live=True)
    case_str = str(case_path.resolve())
    jobs = refresh_jobs(case_path)
    active_jobs = [job for job in jobs if job.get("status") in {"running", "paused"}]
    tracked_pids = set(_running_job_pids(active_jobs))
    launcher_pids = {
        int(row["pid"])
        for row in snapshot["untracked_processes"]
        if str(row.get("case", "")) == case_str
        and str(row.get("role")) == "launcher"
        and int(row.get("pid", 0)) > 0
    }

    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in snapshot["untracked_processes"]:
        pid = int(row.get("pid", 0) or 0)
        if pid <= 0:
            continue
        if str(row.get("case", "")) != case_str:
            continue
        role = str(row.get("role", "solver"))
        launcher_pid = row.get("launcher_pid")
        if role == "solver" and isinstance(launcher_pid, int) and launcher_pid in launcher_pids:
            # The launcher process represents this solver subtree.
            continue
        if pid in tracked_pids:
            skipped.append({"pid": pid, "reason": "already_tracked"})
            continue
        selected.append(
            {
                "pid": pid,
                "role": role,
                "solver": row.get("solver"),
                "command": str(row.get("command") or ""),
                "launcher_pid": launcher_pid if isinstance(launcher_pid, int) else None,
            },
        )

    adopted: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for row in selected:
        pid = int(row["pid"])
        command = str(row.get("command") or "")
        role = str(row.get("role") or "solver")
        solver_name = str(row.get("solver") or "solver")
        name = solver_name if role == "solver" else f"{solver_name}-launcher"
        try:
            job_id = register_job(
                case_path,
                name,
                pid,
                command,
                None,
                kind="solver",
                detached=True,
                extra={"adopted": True, "role": role},
            )
        except OSError as exc:
            failed.append({"pid": pid, "error": str(exc)})
            continue
        adopted.append(
            {
                "id": job_id,
                "pid": pid,
                "name": name,
                "role": role,
                "command": command,
            },
        )

    return {
        "case": case_str,
        "selected": len(selected),
        "adopted": adopted,
        "failed": failed,
        "skipped": skipped,
        "jobs_running_before": len(active_jobs),
        "jobs_running_after": len(active_jobs) + len(adopted),
    }


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
    return case_status_service.status_payload(
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
            "window": {
                "samples": row.get("samples"),
                "delta": row.get("live_delta"),
            },
            "source": criterion_source(str(row.get("key", ""))),
        }
        for row in rtc.get("criteria", [])
    ]


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
        launcher_set = set(launchers)
        solver_launcher: dict[int, int | None] = {
            int(row["pid"]): (
                launcher_pid if isinstance((launcher_pid := row.get("launcher_pid")), int) else None
            )
            for row in solver_rows
        }
        # Avoid double-signaling workers that are descendants of launcher processes.
        solver_pids = [
            pid
            for pid in solver_pids
            if solver_launcher.get(pid) not in launcher_set
        ]
    signal_code = _signal_number(signal_name)
    stopped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for row in selected_rows:
        pid = int(row.get("pid", 0) or 0)
        role = str(row.get("role") or "solver")
        should_stop = pid in launchers or pid in solver_pids
        if not should_stop:
            continue
        try:
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
        stopped.append(
            {
                "id": None,
                "pid": pid,
                "name": f"untracked-{role}",
                "kind": "untracked",
                "role": role,
                "case": case_str,
                "launcher_pid": row.get("launcher_pid"),
                "solver_pids": row.get("solver_pids", []),
                "command": row.get("command"),
            },
        )
    return {
        "case": case_str,
        "selected": len(stopped) + len(failed),
        "stopped": stopped,
        "failed": failed,
        "launcher_pids": launchers,
        "solver_pids": solver_pids,
    }


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
    try:
        return runtime_control_service.runtime_control_snapshot(
            case_path,
            solver,
            resolve_log_source_fn=case_source_service.resolve_log_source,
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
    )


def _run_time_control_data(
    case_path: Path,
    log_text: str,
) -> runtime_control_service.RunTimeControlPayload:
    return runtime_control_service.run_time_control_data(case_path, log_text)


def _read_with_local_includes(
    path: Path,
    *,
    case_root: Path | None = None,
    _seen: set[Path] | None = None,
) -> str:
    return runtime_control_service.read_with_local_includes(
        path,
        case_root=case_root,
        seen=_seen,
    )


def _strip_include_token(value: str) -> str:
    return runtime_control_service.strip_include_token(value)


def _resolve_include_path(
    include_kind: str,
    include_raw: str,
    include_parent: Path,
    case_root: Path,
) -> Path | None:
    return runtime_control_service.resolve_include_path(
        include_kind,
        include_raw,
        include_parent,
        case_root,
    )


def _strip_comments(text: str) -> str:
    return runtime_control_service.strip_comments(text)


def _iter_blocks_recursive(text: str, prefix: str = "") -> list[tuple[str, str]]:
    return runtime_control_service.iter_blocks_recursive(text, prefix)


def _iter_named_blocks(text: str) -> list[tuple[str, str]]:
    return runtime_control_service.iter_named_blocks(text)


def _parse_block_name(text: str, start: int) -> tuple[str, int] | None:
    return runtime_control_service.parse_block_name(text, start)


def _matching_brace(text: str, start: int) -> int:
    return runtime_control_service.matching_brace(text, start)


def _first_block_body(text: str, name: str) -> str | None:
    return runtime_control_service.first_block_body(text, name)


def _dedupe_criteria(
    rows: list[runtime_control_service.CriterionRow],
) -> list[runtime_control_service.CriterionRow]:
    return runtime_control_service.dedupe_criteria(rows)


def _inline_criteria(
    clean_text: str,
    log_text: str,
) -> list[runtime_control_service.CriterionRow]:
    return runtime_control_service.inline_criteria(clean_text, log_text)


def _runtime_control_conditions(
    clean_text: str,
    log_text: str,
) -> tuple[float | None, list[runtime_control_service.CriterionRow]]:
    return runtime_control_service.runtime_control_conditions(clean_text, log_text)


def _runtime_control_block_rows(
    block_key: str,
    body: str,
    log_text: str,
) -> list[runtime_control_service.CriterionRow]:
    return runtime_control_service.runtime_control_block_rows(block_key, body, log_text)


def _criterion_status(key: str, log_text: str) -> tuple[str, str | None]:
    return runtime_control_service.criterion_status(key, log_text)


def _eta_seconds(
    latest_time_value: float | None,
    target_time: float | None,
    times: list[float],
    execution_times: list[float],
) -> float | None:
    return runtime_control_service.eta_seconds(
        latest_time_value,
        target_time,
        times,
        execution_times,
    )


def _is_log_fresh(log_path: Path | None, freshness_seconds: float = 90.0) -> bool:
    return runtime_control_service.is_log_fresh(log_path, freshness_seconds)


def _latest_iteration(text: str, fallback: int) -> int | None:
    return runtime_control_service.latest_iteration(text, fallback)


def _first_match(text: str, pattern: re.Pattern[str]) -> str | None:
    return runtime_control_service.first_match(text, pattern)


def _last_float(text: str, pattern: re.Pattern[str]) -> float | None:
    return runtime_control_service.last_float(text, pattern)


def _to_float(text: str | None) -> float | None:
    return runtime_control_service.to_float(text)


def _collect_floats(lines: list[str], pattern: re.Pattern[str]) -> list[float]:
    return convergence_service.collect_floats(lines, pattern)


def _band(values: list[float]) -> float | None:
    return convergence_service.band(values)


def _thermo_out_of_range_count(lines: list[str]) -> int:
    return convergence_service.thermo_out_of_range_count(lines)


def _residual_flatline(residuals: dict[str, list[float]]) -> list[str]:
    return convergence_service.residual_flatline(residuals)


def _extract_series(text: str, pattern: str) -> list[float]:
    return convergence_service.extract_series(text, pattern)


def _windowed_stability(
    values: list[float],
    *,
    tolerance: float,
    window: int = 8,
    startup_samples: int = 0,
    comparator: str = "le",
    sec_per_sample: float | None = None,
) -> convergence_service.WindowedStabilityState:
    return convergence_service.windowed_stability(
        values,
        tolerance=tolerance,
        window=window,
        startup_samples=startup_samples,
        comparator=comparator,
        sec_per_sample=sec_per_sample,
    )
