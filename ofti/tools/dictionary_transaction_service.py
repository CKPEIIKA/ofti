from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ofti.core.case_snapshot import write_snapshot_manifest
from ofti.core.entry_io import read_entry, write_entry
from ofti.tools.case_source_service import require_case_dir


def set_entries_payload(
    case_dir: Path,
    edits: list[tuple[str, str, str]],
    *,
    apply: bool = True,
) -> dict[str, Any]:
    case = require_case_dir(case_dir)
    plan = _validate_plan(case, edits)
    rows = [_edit_row(case, path, key, value) for path, key, value in plan]
    payload: dict[str, Any] = {
        "case": str(case),
        "ok": True,
        "applied": False,
        "snapshot": None,
        "edits": rows,
    }
    if not apply:
        return payload
    snapshot = _snapshot_files(case, plan)
    payload["snapshot"] = str(snapshot)
    try:
        _apply_plan(case, plan)
    except (OSError, ValueError) as exc:
        _restore_snapshot(case, snapshot)
        payload.update(ok=False, error=str(exc), rolled_back=True)
        return payload
    payload["applied"] = True
    payload["rolled_back"] = False
    return payload


def _apply_plan(case: Path, plan: list[tuple[Path, str, str]]) -> None:
    for path, key, value in plan:
        if not write_entry(path, key, value):
            raise ValueError(f"failed to set {path.relative_to(case)}:{key}")


def parse_edit_specs(specs: list[str]) -> list[tuple[str, str, str]]:
    edits: list[tuple[str, str, str]] = []
    for spec in specs:
        target, separator, value = spec.partition("=")
        rel_file, key_separator, key = target.partition(":")
        if not separator or not key_separator or not rel_file.strip() or not key.strip():
            raise ValueError("edit must use FILE:KEY=VALUE")
        edits.append((rel_file.strip(), key.strip(), value.strip()))
    return edits


def _validate_plan(case: Path, edits: list[tuple[str, str, str]]) -> list[tuple[Path, str, str]]:
    if not edits:
        raise ValueError("at least one dictionary edit is required")
    plan: list[tuple[Path, str, str]] = []
    for rel_file, key, value in edits:
        path = (case / rel_file).resolve()
        if not path.is_relative_to(case):
            raise ValueError(f"dictionary path escapes case: {rel_file}")
        if not path.is_file():
            raise ValueError(f"dictionary not found: {path}")
        if not key:
            raise ValueError("dictionary key cannot be empty")
        plan.append((path, key, value))
    return plan


def _edit_row(case: Path, path: Path, key: str, value: str) -> dict[str, Any]:
    try:
        before = read_entry(path, key)
    except (OSError, RuntimeError, ValueError, KeyError):
        before = None
    return {"file": path.relative_to(case).as_posix(), "key": key, "before": before, "after": value}


def _snapshot_files(case: Path, plan: list[tuple[Path, str, str]]) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = case / ".ofti" / "transactions" / timestamp
    for path in {row[0] for row in plan}:
        destination = snapshot / "inputs" / path.relative_to(case)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    write_snapshot_manifest(
        snapshot,
        case,
        reason="dictionary-transaction",
        roots=tuple(sorted({row[0].relative_to(case).as_posix() for row in plan})),
    )
    return snapshot


def _restore_snapshot(case: Path, snapshot: Path) -> None:
    inputs = snapshot / "inputs"
    for source in inputs.rglob("*"):
        if not source.is_file():
            continue
        destination = case / source.relative_to(inputs)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
