from __future__ import annotations

import re
from pathlib import Path

from ofti.core.entry_io import read_entry, write_entry
from ofti.core.mesh_info import mesh_counts
from ofti.foam.openfoam import OpenFOAMError


def detect_mesh_stats(case_path: Path) -> str:  # noqa: C901
    log_path = latest_checkmesh_log(case_path)
    if log_path is None:
        if has_mesh(case_path):
            cells, faces, points = mesh_counts(case_path)
            if cells or faces or points:
                parts = []
                if cells is not None:
                    parts.append(f"{cells} cells")
                if faces is not None:
                    parts.append(f"faces={faces}")
                if points is not None:
                    parts.append(f"points={points}")
                return ", ".join(parts)
            return "mesh (no checkMesh log)"
        return "unknown"
    try:
        text = _read_log_snippet(log_path)
    except OSError:
        return "mesh (log unreadable)" if has_mesh(case_path) else "unknown"

    cells = parse_cells_count(text)
    skew = _format_float(parse_max_skewness(text))
    non_orth = _format_float(parse_max_non_orth(text))
    parts = []
    if cells:
        parts.append(f"{cells} cells")
    if skew:
        parts.append(f"skew={skew}")
    if non_orth:
        parts.append(f"nonOrth={non_orth}")
    if parts:
        return ", ".join(parts)
    return "mesh (unparsed)" if has_mesh(case_path) else "unknown"


def detect_solver(case_path: Path) -> str:
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        return "unknown"
    try:
        value = read_entry(control_dict, "application")
    except OpenFOAMError:
        return "unknown"
    text = value.strip()
    if not text:
        return "unknown"
    solver = text.split()[0].rstrip(";")
    return solver or "unknown"


def read_application(control_dict: Path) -> str:
    return read_entry(control_dict, "application")


def read_number_of_subdomains(decompose_dict: Path) -> int | None:
    try:
        number = read_entry(decompose_dict, "numberOfSubdomains").strip().rstrip(";")
    except OpenFOAMError:
        return None
    try:
        return int(number) if number else None
    except ValueError:
        return None


def set_start_from_latest(control_dict: Path, latest: str) -> bool:
    ok_start = write_entry(control_dict, "startFrom", "latestTime")
    ok_time = write_entry(control_dict, "startTime", latest)
    return ok_start and ok_time


def detect_parallel_settings(case_path: Path) -> str:
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        return "n/a"
    number = read_optional_entry(decompose_dict, "numberOfSubdomains")
    method = read_optional_entry(decompose_dict, "method")
    if number and method:
        return f"{number} ({method})"
    if number:
        return number
    if method:
        return method
    return "n/a"


def has_mesh(case_path: Path) -> bool:
    boundary = case_path / "constant" / "polyMesh" / "boundary"
    if not boundary.is_file():
        return False
    try:
        return boundary.stat().st_size > 0
    except OSError:
        return True


def latest_checkmesh_log(case_path: Path) -> Path | None:
    candidates = list(case_path.glob("log.checkMesh*"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def parse_cells_count(text: str) -> str | None:
    patterns = [
        r"(?i)number of cells\s*:\s*([0-9eE.+-]+)",
        r"(?i)number of cells\s*:\s*([0-9,]+)",
        r"(?i)cells\s*:\s*([0-9eE.+-]+)",
        r"(?i)cells\s*:\s*([0-9,]+)",
        r"(?i)ncells\s*:\s*([0-9eE.+-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace(",", "")
    return None


def parse_max_skewness(text: str) -> str | None:
    match = re.search(r"(?i)max\s+skewness\s*=\s*([0-9eE.+-]+)", text)
    if match:
        return match.group(1)
    return None


def parse_max_non_orth(text: str) -> str | None:
    patterns = [
        r"(?i)max\s+non-orthogonality\s*=\s*([0-9eE.+-]+)",
        r"(?i)non-orthogonality.*max\s*[:=]\s*([0-9eE.+-]+)",
        r"(?i)non-orthogonality.*max\s+([0-9eE.+-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _read_log_snippet(path: Path, limit: int = 20000) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return path.read_text(errors="ignore")
    if size <= limit:
        return path.read_text(errors="ignore")
    with path.open("r", errors="ignore") as handle:
        head = handle.read(limit)
        try:
            handle.seek(max(0, size - limit))
        except OSError:
            return head
        tail = handle.read(limit)
    return f"{head}\n{tail}"


def preferred_log_name(case_path: Path) -> str:
    solver = detect_solver(case_path)
    if solver and solver != "unknown":
        candidate = case_path / f"log.{solver}"
        if candidate.is_file():
            return candidate.name
    try:
        logs = sorted(case_path.glob("log.*"), key=lambda p: p.stat().st_mtime)
    except OSError:
        logs = []
    if logs:
        return logs[-1].name
    return "none"


def _format_float(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return f"{float(value):.2f}"
    except ValueError:
        return value


def read_optional_entry(file_path: Path, key: str) -> str | None:
    try:
        return read_entry(file_path, key).strip()
    except OpenFOAMError:
        return None
