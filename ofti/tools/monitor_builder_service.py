from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from ofti.tools import case_source_service

SUPPORTED_MONITORS: dict[str, str] = {
    "residuals": """residuals
{
    type            residuals;
    libs            (utilityFunctionObjects);
    fields          (U p k omega);
    writeControl    timeStep;
    writeInterval   1;
}
""",
    "courant": """CourantNo
{
    type            CourantNo;
    libs            (fieldFunctionObjects);
    writeControl    timeStep;
    writeInterval   1;
}
""",
    "yplus": """yPlus
{
    type            yPlus;
    libs            (fieldFunctionObjects);
    writeControl    writeTime;
}
""",
}

DEFAULT_MONITORS: tuple[str, ...] = ("residuals", "courant")


def monitor_builder_payload(
    case_dir: Path,
    *,
    monitors: tuple[str, ...] | list[str] | None = None,
    write: bool = False,
    include_diff: bool = False,
) -> dict[str, Any]:
    """Plan or write a simple functionObject include file for live monitors."""
    case_path = case_source_service.require_case_dir(case_dir)
    selected = _normalize_monitors(monitors)
    target = case_path / "system" / "controlDict.functions"
    text = monitor_config_text(selected)
    old_text = _read_text(target)
    changed = old_text != text
    if write and changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return {
        "case": str(case_path),
        "target": str(target),
        "monitors": [
            {
                "monitor": monitor,
                "status": "written" if write else "planned",
                "writes": "system/controlDict.functions",
                "note": _monitor_note(monitor),
            }
            for monitor in selected
        ],
        "configured": _control_dict_mentions_functions(case_path),
        "changed": changed,
        "written": bool(write),
        "activation": (
            "controlDict already mentions functions"
            if _control_dict_mentions_functions(case_path)
            else "include system/controlDict.functions from controlDict.functions before launch"
        ),
        "diff": _diff_lines(old_text, text, target) if include_diff else [],
    }


def monitor_config_text(monitors: tuple[str, ...] | list[str] | None = None) -> str:
    selected = _normalize_monitors(monitors)
    blocks = [SUPPORTED_MONITORS[monitor].rstrip() for monitor in selected]
    return "\n\n".join(blocks).rstrip() + "\n"


def _normalize_monitors(monitors: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    selected = tuple(monitors or DEFAULT_MONITORS)
    unknown = sorted(set(selected).difference(SUPPORTED_MONITORS))
    if unknown:
        raise ValueError(f"unknown monitor(s): {', '.join(unknown)}")
    return selected


def _control_dict_mentions_functions(case_path: Path) -> bool:
    text = _read_text(case_path / "system" / "controlDict")
    return "functions" in text or "controlDict.functions" in text


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _diff_lines(old_text: str, new_text: str, target: Path) -> list[str]:
    return list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=str(target),
            tofile=str(target),
            lineterm="",
        ),
    )


def _monitor_note(monitor: str) -> str:
    notes = {
        "residuals": "live residual scope fields U/p/k/omega",
        "courant": "live mean/max Courant scope",
        "yplus": "wall yPlus on write times",
    }
    return notes.get(monitor, "functionObject monitor")
