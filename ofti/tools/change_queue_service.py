from __future__ import annotations

from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from ofti.core.case_snapshot import write_case_snapshot
from ofti.foam.subprocess_utils import run_trusted

_CASE_PATHS = ("system", "constant", "0", "0.orig")


def change_queue_payload(
    case_path: Path,
    *,
    max_diff_lines: int = 200,
    write_snapshot: bool = False,
) -> dict[str, Any]:
    """Return a read-only pending-change queue for case dictionaries."""
    rows, source, error = _git_status_rows(case_path)
    diff, diff_error = (
        _git_diff(case_path, max_lines=max_diff_lines)
        if source == "git"
        else ([], None)
    )
    snapshot_path, snapshot_error = _snapshot(case_path) if write_snapshot else (None, None)
    return {
        "case": str(case_path),
        "source": source,
        "count": len(rows),
        "changes": rows,
        "diff": diff,
        "actions": _action_rows(rows, snapshot_path=snapshot_path),
        "snapshot_path": str(snapshot_path) if snapshot_path is not None else None,
        "snapshot_error": snapshot_error,
        "error": error,
        "diff_error": diff_error,
        "paths": list(_CASE_PATHS),
    }


def _git_status_rows(case_path: Path) -> tuple[list[dict[str, str]], str, str | None]:
    try:
        result = run_trusted(
            ["git", "-C", str(case_path), "status", "--short", "--", *_CASE_PATHS],
            text=True,
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (FileNotFoundError, OSError, TimeoutExpired) as exc:
        return [], "git", str(exc)
    if result.returncode != 0:
        return [], "none", (result.stderr or result.stdout).strip() or "not a git worktree"
    rows = [_parse_status_line(line) for line in result.stdout.splitlines() if line.strip()]
    return rows, "git", None


def _parse_status_line(line: str) -> dict[str, str]:
    status = line[:2].strip() or "?"
    path = line[3:].strip() if len(line) > 3 else line.strip()
    if " -> " in path:
        _old, path = path.split(" -> ", 1)
    return {"status": status, "path": path}


def _git_diff(case_path: Path, *, max_lines: int) -> tuple[list[str], str | None]:
    try:
        result = run_trusted(
            ["git", "-C", str(case_path), "diff", "--", *_CASE_PATHS],
            text=True,
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (FileNotFoundError, OSError, TimeoutExpired) as exc:
        return [], str(exc)
    if result.returncode != 0:
        return [], (result.stderr or result.stdout).strip() or "git diff failed"
    lines = result.stdout.splitlines()
    if len(lines) > max_lines:
        return [*lines[:max_lines], f"... {len(lines) - max_lines} more diff lines"], None
    return lines, None


def _action_rows(
    rows: list[dict[str, str]],
    *,
    snapshot_path: Path | None,
) -> list[dict[str, str]]:
    pending = bool(rows)
    snapshot_status = "done" if snapshot_path is not None else "recommended" if pending else "idle"
    if not pending:
        apply_status = "idle"
    elif snapshot_path is None:
        apply_status = "blocked"
    else:
        apply_status = "ready"
    snapshot_target = (
        str(snapshot_path) if snapshot_path is not None else ".ofti/case_snapshot.json"
    )
    return [
        {
            "action": "review-diff",
            "status": "ready" if pending else "idle",
            "target": "VCS diff",
            "requires": "pending case changes",
            "confirm": "inspect diff before any apply/write path",
        },
        {
            "action": "snapshot",
            "status": snapshot_status,
            "target": snapshot_target,
            "requires": "pending case changes",
            "confirm": "snapshot exists before destructive or bulk apply",
        },
        {
            "action": "apply",
            "status": apply_status,
            "target": "queued case edits",
            "requires": "snapshot and reviewed diff",
            "confirm": "apply path must show exact file diff first",
        },
    ]


def _snapshot(case_path: Path) -> tuple[Path | None, str | None]:
    try:
        return write_case_snapshot(case_path), None
    except (OSError, RuntimeError, ValueError) as exc:
        return None, str(exc)
