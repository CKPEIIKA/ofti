"""Campaign payloads (multi-case list/status/rank/stop/keep/compare).

Extracted from knife_service. Cross-calls into knife_service (stop_payload,
compare_payload, status_payload, criteria_satisfaction_eta) go through the lazy
``_service()`` accessor to avoid an import cycle and keep monkeypatch behavior.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from ofti.tools import case_source_service, process_scan_service


def _service() -> Any:
    from ofti.tools import knife_service

    return knife_service


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
            _service().stop_payload(
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
            _service().stop_payload(
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
            diff = _service().compare_payload(
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


def _campaign_glob_paths(root: Path, case_glob: str) -> list[Path]:
    pattern = case_glob.strip() or "*"
    return [path.resolve() for path in root.glob(pattern) if path.is_dir()]


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
    payload = _service().status_payload(
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
        "eta_seconds": _service().criteria_satisfaction_eta(criteria),
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
