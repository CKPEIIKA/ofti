from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ofti.core.case import read_number_of_subdomains
from ofti.core.checkpoint import checkpoint_health
from ofti.core.times import processor_dirs
from ofti.tools.case_source_service import require_case_dir


def checkpoint_payload(case_dir: Path, *, expected_processors: int | None = None) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    health = checkpoint_health(case_path, expected_processors=expected_processors)
    return {
        "case": str(case_path),
        "ok": bool(health["complete_times"]),
        "common": True,
        **health,
    }


def restart_plan_payload(
    case_dir: Path,
    *,
    expected_processors: int | None = None,
    target_processors: int | None = None,
) -> dict[str, Any]:
    """Describe a safe decomposed restart without changing the case."""
    case_path = require_case_dir(case_dir)
    paths = processor_dirs(case_path)
    actual = len(paths)
    configured = read_number_of_subdomains(case_path / "system" / "decomposeParDict")
    expected = expected_processors or configured or actual
    if expected <= 0:
        raise ValueError("unable to determine current MPI size")
    if target_processors is not None and target_processors <= 1:
        raise ValueError("target processor count must be greater than 1")
    health = checkpoint_health(case_path)
    latest_common = health["latest_complete_time"]
    partial_newer = _partial_newer_times(health["partial_times"], latest_common)
    contiguous = [path.name for path in paths] == [f"processor{index}" for index in range(actual)]
    mpi_consistent = actual == expected and configured in {None, expected} and contiguous
    safe_to_apply = bool(paths and latest_common is not None and mpi_consistent)
    unsafe_reasons = _restart_unsafe_reasons(
        has_processors=bool(paths),
        has_checkpoint=latest_common is not None,
        mpi_consistent=mpi_consistent,
    )
    return {
        "case": str(case_path),
        "ok": safe_to_apply,
        "safe_to_apply": safe_to_apply,
        "unsafe_reasons": unsafe_reasons,
        "latest_common_time": latest_common,
        "partial_newer_times": partial_newer,
        "checkpoint": health,
        "mpi": {
            "processor_dirs": [path.name for path in paths],
            "actual": actual,
            "configured": configured,
            "expected": expected,
            "target": target_processors,
            "contiguous": contiguous,
            "consistent": mpi_consistent,
        },
        "plan": _restart_steps(
            case_path,
            latest_common=latest_common,
            partial_newer=partial_newer,
            actual=actual,
            target=target_processors,
        ),
        "mutated": False,
    }


def _restart_unsafe_reasons(
    *,
    has_processors: bool,
    has_checkpoint: bool,
    mpi_consistent: bool,
) -> list[str]:
    checks = (
        (not has_processors, "parallel restart requires processor* directories"),
        (not has_checkpoint, "no complete processor checkpoint is available"),
        (not mpi_consistent, "processor directories and configured MPI size do not agree"),
    )
    return [reason for failed, reason in checks if failed]


def quarantine_partial_payload(
    case_dir: Path,
    *,
    expected_processors: int | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or move partial processor times into case-local quarantine."""
    case_path = require_case_dir(case_dir)
    health = checkpoint_health(case_path, expected_processors=expected_processors)
    quarantine = case_path / ".ofti" / "quarantine" / "checkpoints" / _timestamp()
    moves = _quarantine_moves(case_path, quarantine, health["quarantinable_times"])
    safe_to_apply = bool(health["complete_times"] or not moves)
    payload: dict[str, Any] = {
        "case": str(case_path),
        "ok": True,
        "applied": False,
        "safe_to_apply": safe_to_apply,
        "quarantine": str(quarantine),
        "moves": moves,
        "checkpoint": health,
    }
    if not apply or not moves:
        return payload
    if not safe_to_apply:
        raise ValueError("refusing to quarantine partial times without a complete checkpoint")
    _apply_moves(moves)
    payload["applied"] = True
    payload["checkpoint_after"] = checkpoint_health(
        case_path,
        expected_processors=expected_processors,
    )
    return payload


def _quarantine_moves(
    case_path: Path,
    quarantine: Path,
    time_names: list[str],
) -> list[dict[str, str]]:
    moves: list[dict[str, str]] = []
    for processor in sorted(case_path.glob("processor[0-9]*")):
        if not processor.is_dir():
            continue
        for time_name in time_names:
            source = processor / time_name
            if not source.is_dir():
                continue
            destination = quarantine / processor.name / time_name
            moves.append({"source": str(source), "destination": str(destination)})
    return moves


def _partial_newer_times(
    rows: list[dict[str, Any]],
    latest_common: str | None,
) -> list[dict[str, Any]]:
    if latest_common is None:
        return list(rows)
    common_value = float(latest_common)
    return [row for row in rows if float(str(row["time"])) > common_value]


def _restart_steps(
    case_path: Path,
    *,
    latest_common: str | None,
    partial_newer: list[dict[str, Any]],
    actual: int,
    target: int | None,
) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    if partial_newer:
        steps.append(
            {
                "action": "quarantine-partial",
                "mutates": True,
                "command": f"ofti knife checkpoint {case_path} --quarantine-partial --apply",
                "times": [row["time"] for row in partial_newer],
            },
        )
    steps.append(
        {
            "action": "reconstruct",
            "mutates": True,
            "command": (
                f"reconstructPar -case {case_path} -time {latest_common}" if latest_common is not None else None
            ),
        },
    )
    if target is not None and target != actual:
        steps.extend(
            [
                {
                    "action": "set-subdomains",
                    "mutates": True,
                    "value": target,
                    "file": "system/decomposeParDict",
                },
                {
                    "action": "decompose",
                    "mutates": True,
                    "command": f"decomposePar -case {case_path} -force -latestTime",
                },
            ],
        )
    steps.extend(
        [
            {
                "action": "resume-latest",
                "mutates": True,
                "entries": {
                    "system/controlDict:startFrom": "latestTime",
                    "system/controlDict:stopAt": "endTime",
                },
            },
            {
                "action": "start",
                "mutates": False,
                "processors": target or actual,
            },
        ],
    )
    return steps


def _apply_moves(moves: list[dict[str, str]]) -> None:
    completed: list[tuple[Path, Path]] = []
    try:
        for row in moves:
            source = Path(row["source"])
            destination = Path(row["destination"])
            _require_available_destination(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            completed.append((source, destination))
    except (OSError, ValueError):
        _rollback_moves(completed)
        raise


def _require_available_destination(destination: Path) -> None:
    if destination.exists():
        raise ValueError(f"quarantine destination already exists: {destination}")


def _rollback_moves(completed: list[tuple[Path, Path]]) -> None:
    for source, destination in reversed(completed):
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
