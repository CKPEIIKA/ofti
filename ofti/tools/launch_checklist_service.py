from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.tools import knife_service


def launch_checklist_payload(case_path: Path) -> dict[str, Any]:
    preflight = knife_service.preflight_payload(case_path)
    rows = [
        _row("Case", True, str(case_path), "OpenFOAM case directory selected."),
        _row(
            "controlDict",
            bool(preflight.get("checks", {}).get("system/controlDict")),
            "system/controlDict",
            "Create missing config before launch.",
        ),
        _row(
            "Solver",
            not bool(preflight.get("solver_error")),
            str(preflight.get("solver") or preflight.get("solver_error") or "unknown"),
            "Set system/controlDict application.",
        ),
        _row(
            "Numerics",
            (case_path / "system" / "fvSchemes").is_file()
            and (case_path / "system" / "fvSolution").is_file(),
            "system/fvSchemes + system/fvSolution",
            "Create or validate fvSchemes/fvSolution.",
        ),
        _row(
            "Mesh",
            (case_path / "constant" / "polyMesh").is_dir(),
            "constant/polyMesh",
            "Run mesh generation/checkMesh before solver launch.",
        ),
        _row(
            "Parallel",
            (case_path / "system" / "decomposeParDict").is_file(),
            "system/decomposeParDict",
            "Only needed for parallel launch.",
            required=False,
        ),
        _row(
            "Monitors",
            _control_dict_has_functions(case_path),
            "system/controlDict.functions",
            "Optional but recommended for live telemetry.",
            required=False,
        ),
    ]
    blocking = [row for row in rows if row["required"] and row["status"] != "pass"]
    return {"case": str(case_path), "ready": not blocking, "rows": rows, "blocking": blocking}


def _row(
    item: str,
    ok: bool,
    evidence: str,
    advice: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "item": item,
        "status": "pass" if ok else ("fail" if required else "warn"),
        "required": required,
        "evidence": evidence,
        "advice": advice,
    }


def _control_dict_has_functions(case_path: Path) -> bool:
    path = case_path / "system" / "controlDict"
    if not path.is_file():
        return False
    try:
        return "functions" in path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
