from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ofti.core.boundary import list_field_files, zero_dir
from ofti.core.case import (
    detect_mesh_stats,
    detect_parallel_settings,
    detect_solver,
    preferred_log_name,
)
from ofti.core.case_headers import detect_case_header_version
from ofti.core.entry_io import read_boundary_field, read_dimensions, read_internal_field
from ofti.core.mesh_info import boundary_summary, mesh_counts
from ofti.core.times import latest_time
from ofti.foam.openfoam_env import detect_openfoam_version
from ofti.foamlib import adapter as foamlib_integration

SNAPSHOT_FORMAT = "ofti.snapshot"
SNAPSHOT_FORMAT_VERSION = 1


def build_case_snapshot(case_path: Path) -> dict[str, Any]:
    latest = latest_time(case_path)
    status = "ran" if latest not in ("0", "0.0", "") else "clean"
    cells, faces, points = mesh_counts(case_path)
    summary = boundary_summary(case_path)
    header_version = detect_case_header_version(case_path)
    foam_version = detect_openfoam_version()
    if foam_version == "unknown" and header_version != "unknown":
        foam_version = header_version
    return {
        "case": {
            "name": case_path.name,
            "path": str(case_path),
            "solver": detect_solver(case_path),
            "foam_version": foam_version,
            "case_header_version": header_version,
            "latest_time": latest or "unknown",
            "status": status,
            "parallel": detect_parallel_settings(case_path),
            "log": preferred_log_name(case_path),
        },
        "mesh": {
            "summary": detect_mesh_stats(case_path),
            "cells": cells,
            "faces": faces,
            "points": points,
            "boundary": summary,
        },
        "fields": _field_snapshot(case_path),
        "dictionaries": _dictionary_snapshot(case_path),
    }


def write_case_snapshot(case_path: Path, output: Path | None = None) -> Path:
    if output is None:
        output = case_path / ".ofti" / "case_snapshot.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_case_snapshot(case_path)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return output


def build_snapshot_manifest(
    snapshot_dir: Path,
    case_path: Path,
    *,
    reason: str,
    roots: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build a stable manifest for an OFTI safety snapshot directory."""
    root = snapshot_dir.resolve()
    return {
        "format": SNAPSHOT_FORMAT,
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "created_at": _snapshot_timestamp(),
        "reason": reason,
        "case_dir": str(case_path),
        "roots": list(roots),
        "files": _snapshot_files(root),
    }


def write_snapshot_manifest(
    snapshot_dir: Path,
    case_path: Path,
    *,
    reason: str,
    roots: tuple[str, ...] = (),
    output: Path | None = None,
) -> Path:
    if output is None:
        output = snapshot_dir / "snapshot.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_snapshot_manifest(snapshot_dir, case_path, reason=reason, roots=roots)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output


def _field_snapshot(case_path: Path) -> dict[str, dict[str, str]]:
    fields: dict[str, dict[str, str]] = {}
    for name in list_field_files(case_path):
        file_path = zero_dir(case_path) / name
        try:
            dimensions = read_dimensions(file_path)
        except Exception:
            dimensions = ""
        try:
            internal_field = read_internal_field(file_path)
        except Exception:
            internal_field = ""
        try:
            boundary_field = read_boundary_field(file_path)
        except Exception:
            boundary_field = ""
        fields[name] = {
            "dimensions": dimensions,
            "internal_field": internal_field,
            "boundary_field": boundary_field,
        }
    return fields


def _dictionary_snapshot(case_path: Path) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}
    for relative in (
        Path("system/controlDict"),
        Path("system/fvSchemes"),
        Path("system/fvSolution"),
        Path("system/decomposeParDict"),
        Path("constant/transportProperties"),
        Path("constant/turbulenceProperties"),
    ):
        file_path = case_path / relative
        if not file_path.is_file():
            continue
        data = foamlib_integration.read_file_dict(file_path, include_header=True)
        if data:
            snapshot[relative.as_posix()] = data
    return snapshot


def _snapshot_files(snapshot_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not snapshot_dir.exists():
        return rows
    for path in sorted(snapshot_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(snapshot_dir).as_posix()
        rows.append({"path": rel, "size": path.stat().st_size, "sha256": _sha256(path)})
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
