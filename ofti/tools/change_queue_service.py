from __future__ import annotations

from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from ofti.foam.subprocess_utils import run_trusted

_CASE_PATHS = ("system", "constant", "0", "0.orig")


def change_queue_payload(case_path: Path, *, max_diff_lines: int = 200) -> dict[str, Any]:
    """Return a read-only pending-change queue for case dictionaries."""
    rows, source, error = _git_status_rows(case_path)
    diff, diff_error = (
        _git_diff(case_path, max_lines=max_diff_lines)
        if source == "git"
        else ([], None)
    )
    return {
        "case": str(case_path),
        "source": source,
        "count": len(rows),
        "changes": rows,
        "diff": diff,
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
