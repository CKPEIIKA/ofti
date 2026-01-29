from __future__ import annotations

import re
from pathlib import Path

from ofti.core.entry_io import read_entry, write_entry
from ofti.foam.openfoam import OpenFOAMError


def detect_mesh_stats(case_path: Path) -> str:  # noqa: PLR0911
    log_path = latest_checkmesh_log(case_path)
    if log_path is None:
        if has_mesh(case_path):
            return "mesh (no checkMesh log)"
        return "unknown"
    try:
        text = log_path.read_text(errors="ignore")
    except OSError:
        return "mesh (log unreadable)" if has_mesh(case_path) else "unknown"

    cells = parse_cells_count(text)
    skew = parse_max_skewness(text)
    if cells and skew:
        return f"cells={cells}, skew={skew}"
    if cells:
        return f"cells={cells}"
    if skew:
        return f"skew={skew}"
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


def read_optional_entry(file_path: Path, key: str) -> str | None:
    try:
        return read_entry(file_path, key).strip()
    except OpenFOAMError:
        return None
