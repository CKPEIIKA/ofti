from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ofti.core.case import has_mesh, latest_checkmesh_log
from ofti.core.mesh_info import mesh_counts

_READ_LIMIT = 200_000


def mesh_radar_payload(case_path: Path) -> dict[str, Any]:
    log_path = latest_checkmesh_log(case_path)
    payload: dict[str, Any] = {
        "case": str(case_path),
        "log": str(log_path) if log_path else None,
        "has_mesh": has_mesh(case_path),
        "status": "unknown",
        "metrics": [],
        "notes": [],
    }
    if log_path is None:
        cells, faces, points = mesh_counts(case_path)
        payload["metrics"] = _count_metrics(cells=cells, faces=faces, points=points)
        payload["notes"] = ["No checkMesh log found."]
        payload["status"] = "mesh" if payload["has_mesh"] else "missing"
        return payload

    text = _read_text_window(log_path)
    lower = text.lower()
    status = "ok" if "mesh ok" in lower else "warn"
    failed = _first_number(text, [r"(?i)failed\s+(\d+)\s+mesh checks"])
    if failed and failed != "0":
        status = "fail"
    payload["status"] = status
    payload["metrics"] = [
        *_count_metrics(
            cells=_as_int(_first_number(text, [r"(?i)number of cells\s*:\s*([0-9,]+)"])),
            faces=_as_int(_first_number(text, [r"(?i)number of faces\s*:\s*([0-9,]+)"])),
            points=_as_int(_first_number(text, [r"(?i)number of points\s*:\s*([0-9,]+)"])),
        ),
        _quality_metric(
            "Max non-orth",
            _as_float(
                _first_number(
                    text,
                    [
                        r"(?i)max\s+non-orthogonality\s*=\s*([0-9eE.+-]+)",
                        r"(?i)non-orthogonality.*max\s*[:=]\s*([0-9eE.+-]+)",
                    ],
                ),
            ),
            warn=65.0,
            fail=80.0,
        ),
        _quality_metric(
            "Max skewness",
            _as_float(_first_number(text, [r"(?i)max\s+skewness\s*=\s*([0-9eE.+-]+)"])),
            warn=4.0,
            fail=20.0,
        ),
        _quality_metric(
            "Max aspect",
            _as_float(_first_number(text, [r"(?i)max\s+aspect\s+ratio\s*=\s*([0-9eE.+-]+)"])),
            warn=100.0,
            fail=1_000.0,
        ),
        _quality_metric(
            "Min volume",
            _as_float(_first_number(text, [r"(?i)min\s+volume\s*=\s*([0-9eE.+-]+)"])),
            warn=None,
            fail=0.0,
            lower_is_worse=True,
        ),
    ]
    if failed:
        payload["notes"] = [f"Failed checks: {failed}"]
    return payload


def _count_metrics(
    *,
    cells: int | None,
    faces: int | None,
    points: int | None,
) -> list[dict[str, Any]]:
    return [
        {"metric": "Cells", "value": cells, "status": "info", "bar_value": cells, "bar_max": cells},
        {"metric": "Faces", "value": faces, "status": "info", "bar_value": faces, "bar_max": faces},
        {
            "metric": "Points",
            "value": points,
            "status": "info",
            "bar_value": points,
            "bar_max": points,
        },
    ]


def _quality_metric(
    metric: str,
    value: float | None,
    *,
    warn: float | None,
    fail: float | None,
    lower_is_worse: bool = False,
) -> dict[str, Any]:
    status = "unknown"
    if value is not None:
        status = "ok"
        if lower_is_worse:
            if fail is not None and value <= fail:
                status = "fail"
            elif warn is not None and value <= warn:
                status = "warn"
        elif fail is not None and value >= fail:
            status = "fail"
        elif warn is not None and value >= warn:
            status = "warn"
    top = fail or warn or value
    return {"metric": metric, "value": value, "status": status, "bar_value": value, "bar_max": top}


def _first_number(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace(",", "")
    return None


def _as_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _read_text_window(path: Path) -> str:
    size = path.stat().st_size
    if size <= _READ_LIMIT:
        return path.read_text(errors="ignore")
    with path.open("r", errors="ignore") as handle:
        head = handle.read(_READ_LIMIT // 2)
        handle.seek(max(0, size - (_READ_LIMIT // 2)))
        tail = handle.read(_READ_LIMIT // 2)
    return f"{head}\n{tail}"
