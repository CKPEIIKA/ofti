from __future__ import annotations

import os
import re
import shutil
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
)
from ofti.tools.case_doctor import build_case_doctor_report
from ofti.tools.job_registry import refresh_jobs
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


def current_payload(case_dir: Path) -> case_status_service.CurrentPayload:
    case_path = case_source_service.require_case_dir(case_dir)
    return case_status_service.current_payload(
        case_path,
        resolve_solver_name_fn=resolve_solver_name,
        refresh_jobs_fn=refresh_jobs,
        running_job_pids_fn=_running_job_pids,
        scan_proc_solver_processes_fn=_scan_proc_solver_processes,
    )


def compare_payload(left_case: Path, right_case: Path) -> dict[str, Any]:
    left = case_source_service.require_case_dir(left_case)
    right = case_source_service.require_case_dir(right_case)
    diffs = compare_case_dicts(left, right)
    return {
        "left_case": str(left),
        "right_case": str(right),
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
