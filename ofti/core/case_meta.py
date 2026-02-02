from __future__ import annotations

import os
from pathlib import Path

from ofti.core.case import (
    detect_mesh_stats,
    detect_parallel_settings,
    detect_solver,
    preferred_log_name,
)
from ofti.core.case_headers import detect_case_header_version
from ofti.core.mesh_info import mesh_counts
from ofti.core.times import latest_time
from ofti.foam.openfoam_env import detect_openfoam_version


def case_metadata(case_path: Path) -> dict[str, str]:
    latest = latest_time(case_path)
    status = "ran" if latest not in ("0", "0.0", "") else "clean"
    parallel = detect_parallel_settings(case_path)
    mesh = detect_mesh_stats(case_path)
    cells, faces, points = mesh_counts(case_path)
    header_version = detect_case_header_version(case_path)
    foam_version = detect_openfoam_version()
    if foam_version == "unknown" and header_version != "unknown":
        foam_version = header_version
    return {
        "case_name": case_path.name,
        "case_path": str(case_path),
        "solver": detect_solver(case_path),
        "foam_version": foam_version,
        "case_header_version": header_version,
        "latest_time": latest,
        "status": status,
        "mesh": mesh,
        "cells": str(cells) if cells is not None else "n/a",
        "faces": str(faces) if faces is not None else "n/a",
        "points": str(points) if points is not None else "n/a",
        "disk": _format_bytes(_directory_size(case_path)),
        "parallel": parallel,
        "log": preferred_log_name(case_path),
    }


def case_metadata_quick(case_path: Path) -> dict[str, str]:
    latest = latest_time(case_path)
    status = "ran" if latest not in ("0", "0.0", "") else "clean"
    cells, faces, points = mesh_counts(case_path)
    header_version = detect_case_header_version(case_path)
    foam_version = detect_openfoam_version()
    if foam_version == "unknown" and header_version != "unknown":
        foam_version = header_version
    return {
        "case_name": case_path.name,
        "case_path": str(case_path),
        "solver": detect_solver(case_path),
        "foam_version": foam_version,
        "case_header_version": header_version,
        "latest_time": latest or "unknown",
        "status": status,
        "mesh": detect_mesh_stats(case_path),
        "cells": str(cells) if cells is not None else "n/a",
        "faces": str(faces) if faces is not None else "n/a",
        "points": str(points) if points is not None else "n/a",
        "disk": _format_bytes(_directory_size(case_path)),
        "parallel": detect_parallel_settings(case_path),
        "log": preferred_log_name(case_path),
    }


def _directory_size(root: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


def _format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024.0
    return f"{value:.1f}{units[-1]}"
