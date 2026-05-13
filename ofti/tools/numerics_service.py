from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.entry_io import list_keywords, read_entry

_NUMERICS_FILES = ("system/fvSchemes", "system/fvSolution", "system/controlDict")
_CONTROL_KEYS = ("application", "startTime", "endTime", "deltaT", "writeInterval")
_FVSOLUTION_KEYS = ("solvers", "SIMPLE", "PIMPLE", "PISO", "relaxationFactors")


def numerics_payload(case_path: Path) -> dict[str, Any]:
    return {
        "case": str(case_path),
        "files": [_file_row(case_path / rel, rel) for rel in _NUMERICS_FILES],
        "controls": _entry_rows(case_path / "system" / "controlDict", _CONTROL_KEYS),
        "solution": _entry_rows(case_path / "system" / "fvSolution", _FVSOLUTION_KEYS),
    }


def _file_row(path: Path, rel: str) -> dict[str, Any]:
    if not path.is_file():
        return {"file": rel, "status": "missing", "keys": ""}
    try:
        keys = list_keywords(path)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"file": rel, "status": "unreadable", "keys": "", "error": str(exc)}
    return {"file": rel, "status": "ok", "keys": ", ".join(keys[:8])}


def _entry_rows(path: Path, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in keys:
        value = _safe_read(path, key)
        rows.append(
            {
                "key": key,
                "value": value if value is not None else "-",
                "status": "set" if value is not None else "missing",
            },
        )
    return rows


def _safe_read(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    try:
        value = read_entry(path, key).strip()
    except (OSError, RuntimeError, ValueError):
        return None
    return " ".join(value.split())[:120]
