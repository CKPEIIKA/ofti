from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import unified_diff
from pathlib import Path
from typing import Any

from ofti.core.case_snapshot import write_snapshot_manifest
from ofti.core.entry_io import (
    display_entry_value,
    read_entry,
    record_entry_edit,
    updated_entry_text,
)
from ofti.tools.case_source_service import require_case_dir

FORMAT = "ofti.dictionary-transaction"
FORMAT_VERSION = 1


@dataclass(frozen=True)
class _FilePlan:
    path: Path
    relative: str
    before: str
    after: str
    diff: str


def set_entries_payload(
    case_dir: Path,
    edits: list[tuple[str, str, str]],
    *,
    apply: bool = True,
    allow_insert: bool = False,
) -> dict[str, Any]:
    case = require_case_dir(case_dir)
    plan = _validate_plan(case, edits)
    rows = [_edit_row(case, path, key, value, allow_insert=allow_insert) for path, key, value in plan]
    files = _render_file_plans(case, plan)
    payload: dict[str, Any] = {
        "case": str(case),
        "ok": True,
        "applied": False,
        "atomic": True,
        "snapshot": None,
        "manifest": None,
        "edits": rows,
        "diffs": [{"file": item.relative, "diff": item.diff} for item in files],
        "diff": "".join(item.diff for item in files),
    }
    if not apply:
        return payload
    snapshot = _snapshot_files(case, plan)
    payload["snapshot"] = str(snapshot)
    manifest: Path | None = None
    try:
        _stage_files(snapshot, files)
        _apply_staged_files(snapshot, files)
        payload.update(applied=True, rolled_back=False)
        manifest = _write_transaction_manifest(case, snapshot, payload, files)
    except OSError as exc:
        _restore_snapshot(case, snapshot)
        payload.update(ok=False, applied=False, error=str(exc), rolled_back=True)
        try:
            manifest = _write_transaction_manifest(case, snapshot, payload, files)
        except OSError:
            manifest = None
    else:
        _record_edits(plan, rows)
    payload["manifest"] = str(manifest) if manifest is not None else None
    return payload


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


def _edit_row(
    case: Path,
    path: Path,
    key: str,
    value: str,
    *,
    allow_insert: bool,
) -> dict[str, Any]:
    try:
        before = read_entry(path, key)
    except (OSError, RuntimeError, ValueError, KeyError):
        before = None
    relative = path.relative_to(case).as_posix()
    existed = before is not None
    if not existed and not allow_insert:
        raise ValueError(f"key path not found: {relative}:{key}; use --insert to create it")
    return {
        "file": relative,
        "key": key,
        "before": display_entry_value(before) if before is not None else None,
        "after": display_entry_value(value),
        "existed": existed,
        "operation": "update" if existed else "insert",
    }


def _render_file_plans(
    case: Path,
    edits: list[tuple[Path, str, str]],
) -> list[_FilePlan]:
    by_path: dict[Path, list[tuple[str, str]]] = {}
    for path, key, value in edits:
        by_path.setdefault(path, []).append((key, value))
    plans: list[_FilePlan] = []
    for path, file_edits in by_path.items():
        before = path.read_text(encoding="utf-8")
        after = before
        for key, value in file_edits:
            updated = updated_entry_text(after, key, value)
            if updated is None:
                raise ValueError(f"failed to plan source-preserving edit {path.relative_to(case)}:{key}")
            after = updated
        relative = path.relative_to(case).as_posix()
        diff = "".join(
            unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"{relative}.before",
                tofile=f"{relative}.after",
            ),
        )
        plans.append(_FilePlan(path, relative, before, after, diff))
    return plans


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


def _stage_files(snapshot: Path, files: list[_FilePlan]) -> None:
    for item in files:
        staged = snapshot / "staged" / item.relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.path, staged)
        with staged.open("w", encoding="utf-8", newline="") as handle:
            handle.write(item.after)
            handle.flush()
            os.fsync(handle.fileno())


def _apply_staged_files(snapshot: Path, files: list[_FilePlan]) -> None:
    for item in files:
        _replace_staged_file(snapshot / "staged" / item.relative, item.path)


def _replace_staged_file(staged: Path, destination: Path) -> None:
    staged.replace(destination)


def _restore_snapshot(case: Path, snapshot: Path) -> None:
    inputs = snapshot / "inputs"
    for source in inputs.rglob("*"):
        if not source.is_file():
            continue
        destination = case / source.relative_to(inputs)
        temporary = destination.with_name(f".{destination.name}.ofti-restore")
        shutil.copy2(source, temporary)
        temporary.replace(destination)


def _record_edits(
    plan: list[tuple[Path, str, str]],
    rows: list[dict[str, Any]],
) -> None:
    for (path, key, value), row in zip(plan, rows, strict=True):
        before = row["before"]
        record_entry_edit(path, key, str(before) if before is not None else None, value)


def _write_transaction_manifest(
    case: Path,
    snapshot: Path,
    payload: dict[str, Any],
    files: list[_FilePlan],
) -> Path:
    created_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "created_at": created_at,
        "case": str(case),
        "applied": payload["applied"],
        "rolled_back": payload.get("rolled_back", False),
        "snapshot": str(snapshot),
        "edits": payload["edits"],
        "files": [
            {
                "path": item.relative,
                "before_sha256": _sha256_text(item.before),
                "after_sha256": _sha256_text(item.after),
                "diff": item.diff,
            }
            for item in files
        ],
    }
    path = snapshot / "transaction.json"
    _write_json_atomic(path, manifest)
    _write_json_atomic(case / ".ofti" / "transactions" / "latest.json", manifest)
    return path


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
