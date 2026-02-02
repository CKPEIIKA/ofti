from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ofti.core.mesh_info import boundary_summary, mesh_counts


@dataclass(frozen=True)
class CaseReport:
    cells: int | None
    faces: int | None
    points: int | None
    patches: int
    patch_type_counts: Mapping[str, int]


def collect_case_report(case_path: Path) -> CaseReport:
    cells, faces, points = mesh_counts(case_path)
    summary = boundary_summary(case_path)
    types: dict[str, int] = summary.get("types", {})
    return CaseReport(
        cells=cells,
        faces=faces,
        points=points,
        patches=summary.get("patches", 0),
        patch_type_counts=types,
    )
