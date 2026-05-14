from __future__ import annotations

from difflib import unified_diff
from pathlib import Path
from typing import Any

from ofti.core.entry_io import list_keywords, read_entry

_NUMERICS_FILES = ("system/fvSchemes", "system/fvSolution", "system/controlDict")
_CONTROL_KEYS = ("application", "startTime", "endTime", "deltaT", "writeInterval")
_FVSOLUTION_KEYS = ("solvers", "SIMPLE", "PIMPLE", "PISO", "relaxationFactors")


def numerics_payload(case_path: Path) -> dict[str, Any]:
    controls = _entry_rows(case_path / "system" / "controlDict", _CONTROL_KEYS)
    solution = _entry_rows(case_path / "system" / "fvSolution", _FVSOLUTION_KEYS)
    schemes = _entry_rows(
        case_path / "system" / "fvSchemes",
        ("ddtSchemes", "gradSchemes", "divSchemes", "laplacianSchemes"),
    )
    return {
        "case": str(case_path),
        "files": [_file_row(case_path / rel, rel) for rel in _NUMERICS_FILES],
        "controls": controls,
        "solution": solution,
        "schemes": schemes,
        "convergence_contract": _convergence_contract(solution),
        "presets": _preset_rows(case_path),
        "diff_before_write": True,
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


def _convergence_contract(solution_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in solution_rows:
        key = str(row.get("key"))
        value = str(row.get("value") or "")
        if key not in {"SIMPLE", "PIMPLE", "PISO"} or row.get("status") != "set":
            continue
        status = "set" if "residualControl" in value else "missing"
        rows.append(
            {
                "algorithm": key,
                "residualControl": status,
                "source": "system/fvSolution",
            },
        )
    if rows:
        return rows
    return [{"algorithm": "-", "residualControl": "missing", "source": "system/fvSolution"}]


def _preset_rows(case_path: Path) -> list[dict[str, Any]]:
    presets = [
        (
            "conservative steady RANS",
            "Prefer stability over speed for SIMPLE/RANS cases.",
            [
                (
                    "system/fvSolution",
                    "relaxationFactors",
                    "{ fields { p 0.3; } equations { U 0.5; } }",
                ),
                (
                    "system/fvSchemes",
                    "divSchemes",
                    "{ default none; div(phi,U) bounded Gauss upwind; }",
                ),
            ],
        ),
        (
            "faster steady RANS",
            "Looser relaxation for cases that already converge cleanly.",
            [
                (
                    "system/fvSolution",
                    "relaxationFactors",
                    "{ fields { p 0.4; } equations { U 0.7; } }",
                ),
                (
                    "system/fvSchemes",
                    "divSchemes",
                    "{ default none; div(phi,U) bounded Gauss linearUpwind grad(U); }",
                ),
            ],
        ),
        (
            "transient PIMPLE stable",
            "Safer transient controls with bounded first-order convection.",
            [
                ("system/fvSolution", "PIMPLE", "{ nOuterCorrectors 2; nCorrectors 2; }"),
                ("system/fvSchemes", "ddtSchemes", "{ default Euler; }"),
            ],
        ),
    ]
    return [
        {
            "name": name,
            "description": description,
            "changes": _preset_changes(case_path, changes),
            "diff": _preset_diff(case_path, name, changes),
        }
        for name, description, changes in presets
    ]


def _preset_changes(
    case_path: Path,
    changes: list[tuple[str, str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for rel_file, key, proposed in changes:
        current = _safe_read(case_path / rel_file, key) or "<missing>"
        rows.append(
            {
                "file": rel_file,
                "key": key,
                "current": current,
                "proposed": proposed,
            },
        )
    return rows


def _preset_diff(
    case_path: Path,
    preset_name: str,
    changes: list[tuple[str, str, str]],
) -> list[str]:
    before = []
    after = []
    for rel_file, key, proposed in changes:
        current = _safe_read(case_path / rel_file, key) or "<missing>"
        before.append(f"{rel_file}:{key} {current}\n")
        after.append(f"{rel_file}:{key} {proposed}\n")
    return list(
        unified_diff(
            before,
            after,
            fromfile="current numerics",
            tofile=f"preset: {preset_name}",
            lineterm="",
        ),
    )
