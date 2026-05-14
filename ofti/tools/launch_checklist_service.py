from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.tools import knife_service


def launch_checklist_payload(case_path: Path) -> dict[str, Any]:
    preflight = knife_service.preflight_payload(case_path)
    solver = str(preflight.get("solver") or preflight.get("solver_error") or "unknown")
    rows = [
        _row("Case", True, str(case_path), "OpenFOAM case directory selected."),
        _row(
            "controlDict",
            bool(preflight.get("checks", {}).get("system/controlDict")),
            "system/controlDict",
            "Create missing config before launch.",
            open_target="system/controlDict",
        ),
        _row(
            "Solver",
            not bool(preflight.get("solver_error")),
            solver,
            "Set system/controlDict application.",
            open_target="system/controlDict",
        ),
        _row(
            "Numerics",
            (case_path / "system" / "fvSchemes").is_file()
            and (case_path / "system" / "fvSolution").is_file(),
            "system/fvSchemes + system/fvSolution",
            "Create or validate fvSchemes/fvSolution.",
            open_target="system/fvSolution",
        ),
        _row(
            "Mesh",
            (case_path / "constant" / "polyMesh").is_dir(),
            "constant/polyMesh",
            "Run mesh generation/checkMesh before solver launch.",
            open_target="constant/polyMesh",
        ),
        _row(
            "Parallel",
            (case_path / "system" / "decomposeParDict").is_file(),
            "system/decomposeParDict",
            "Only needed for parallel launch.",
            required=False,
            open_target="system/decomposeParDict",
        ),
        _row(
            "Monitors",
            _control_dict_has_functions(case_path),
            "system/controlDict.functions",
            "Optional but recommended for live telemetry.",
            required=False,
            open_target="system/controlDict.functions",
        ),
    ]
    blocking = [row for row in rows if row["required"] and row["status"] != "pass"]
    ready = not blocking
    return {
        "case": str(case_path),
        "solver": solver,
        "ready": ready,
        "gate": "GO" if ready else "NO-GO",
        "rows": rows,
        "blocking": blocking,
        "log_strategy": _log_strategy(case_path, solver),
        "actions": _launch_actions(rows, ready=ready),
    }


def _row(
    item: str,
    ok: bool,
    evidence: str,
    advice: str,
    *,
    required: bool = True,
    open_target: str | None = None,
) -> dict[str, Any]:
    return {
        "item": item,
        "status": "pass" if ok else ("fail" if required else "warn"),
        "required": required,
        "evidence": evidence,
        "advice": advice,
        "open": open_target or evidence,
    }


def _control_dict_has_functions(case_path: Path) -> bool:
    path = case_path / "system" / "controlDict"
    if not path.is_file():
        return False
    try:
        return "functions" in path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def _log_strategy(case_path: Path, solver: str) -> dict[str, Any]:
    log_name = f"log.{solver}" if solver and solver != "unknown" else "log.solver"
    log_path = case_path / log_name
    return {
        "log": log_name,
        "exists": log_path.exists(),
        "rotate_before_launch": log_path.exists(),
        "archive_suffix": ".old",
    }


def _launch_actions(rows: list[dict[str, Any]], *, ready: bool) -> list[dict[str, Any]]:
    if ready:
        return [
            {
                "key": "L",
                "action": "launch",
                "target": "solver",
                "safe": False,
                "reason": "All required launch checks passed.",
            },
            {
                "key": "D",
                "action": "dry-run",
                "target": "solver command",
                "safe": True,
                "reason": "Preview command and prelaunch steps without writing.",
            },
        ]
    return [
        {
            "key": str(index),
            "action": "open failing item",
            "target": str(row.get("open") or row.get("evidence") or row.get("item")),
            "safe": True,
            "reason": str(row.get("advice") or "Fix required launch check."),
        }
        for index, row in enumerate(
            (row for row in rows if row["required"] and row["status"] != "pass"),
            start=1,
        )
    ]
