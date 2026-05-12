from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

_DEFAULT_ROOTS = ("system", "constant", "0")
_DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024


def case_fingerprint(
    case_path: Path,
    *,
    roots: tuple[str, ...] = _DEFAULT_ROOTS,
    max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
) -> dict[str, Any]:
    digest = hashlib.sha256()
    files = 0
    skipped = 0
    for root_name in roots:
        root = case_path / root_name
        if not root.exists():
            continue
        for path in _iter_files(root):
            rel = path.relative_to(case_path).as_posix()
            try:
                stat = path.stat()
            except OSError:
                skipped += 1
                continue
            if stat.st_size > max_file_bytes:
                digest.update(f"skip\0{rel}\0{stat.st_size}\0".encode())
                skipped += 1
                continue
            digest.update(f"file\0{rel}\0{stat.st_size}\0".encode())
            try:
                digest.update(path.read_bytes())
            except OSError:
                skipped += 1
                continue
            files += 1
    return {
        "hash": digest.hexdigest()[:16],
        "files": files,
        "skipped": skipped,
        "roots": list(roots),
    }


def _iter_files(root: Path) -> list[Path]:
    try:
        return sorted(path for path in root.rglob("*") if path.is_file())
    except OSError:
        return []
