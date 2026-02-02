from __future__ import annotations

from pathlib import Path

from ofti.core.case import detect_solver
from ofti.tools.runner import load_postprocessing_presets, load_tool_presets


def base_tools(case_path: Path) -> list[tuple[str, list[str]]]:
    tools = [
        ("blockMesh", ["blockMesh"]),
        ("snappyHexMesh", ["snappyHexMesh"]),
        ("checkMesh", ["checkMesh"]),
        ("setFields", ["setFields"]),
        ("topoSet", ["topoSet"]),
        ("decomposePar", ["decomposePar"]),
        ("reconstructPar", ["reconstructPar"]),
        ("reconstructPar -latestTime", ["reconstructPar", "-latestTime"]),
        ("renumberMesh", ["renumberMesh"]),
        ("transformPoints", ["transformPoints"]),
        ("postProcess -latestTime", ["postProcess", "-latestTime"]),
        ("foamCalc", ["foamCalc"]),
    ]
    solver = detect_solver(case_path)
    if solver and solver != "unknown":
        tools.append((f"runSolver ({solver})", [solver]))
    return tools


def tool_catalog(case_path: Path) -> list[tuple[str, list[str]]]:
    base = base_tools(case_path)
    extra = load_tool_presets(case_path)
    post = [(f"[post] {name}", cmd) for name, cmd in load_postprocessing_presets(case_path)]
    return base + extra + post
