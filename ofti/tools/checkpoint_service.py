from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ofti.core.checkpoint import checkpoint_health
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
