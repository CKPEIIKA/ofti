from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ofti.foam import openfoam


def list_keywords(file_path: Path) -> list[str]:
    return openfoam.list_keywords(file_path)


def list_subkeys(file_path: Path, entry: str) -> list[str]:
    return openfoam.list_subkeys(file_path, entry)


def read_entry(file_path: Path, key: str) -> str:
    return openfoam.read_entry(file_path, key)


def write_entry(file_path: Path, key: str, value: str) -> bool:
    old_value: str | None = None
    try:
        old_value = openfoam.read_entry(file_path, key)
    except Exception:
        old_value = None

    ok = openfoam.write_entry(file_path, key, value)
    if ok:
        _log_entry_edit(file_path, key, old_value, value)
    return ok


def _find_case_root(file_path: Path) -> Path | None:
    for parent in file_path.resolve().parents:
        if (parent / "system" / "controlDict").exists():
            return parent
    return None


def _compact_value(value: str | None, *, max_len: int = 120) -> str:
    if value is None:
        return "<unknown>"
    text = " ".join(value.splitlines()).strip()
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text or "<empty>"


def _log_entry_edit(file_path: Path, key: str, old: str | None, new: str) -> None:
    case_root = _find_case_root(file_path)
    if case_root is None:
        return
    try:
        rel = file_path.relative_to(case_root).as_posix()
    except ValueError:
        rel = file_path.name
    log_dir = case_root / ".ofti"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "edits.log"
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        old_text = _compact_value(old)
        new_text = _compact_value(new)
        line = f"{timestamp} {rel} {key}: {old_text} -> {new_text}\n"
        with log_path.open("a", encoding="utf-8", errors="ignore") as handle:
            handle.write(line)
    except OSError:
        return
