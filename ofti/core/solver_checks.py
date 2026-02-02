from __future__ import annotations

from pathlib import Path

from ofti.core.boundary import list_field_files
from ofti.core.entry_io import read_entry
from ofti.foam.openfoam import OpenFOAMError


def resolve_solver_name(case_path: Path) -> tuple[str | None, str | None]:
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        return None, "system/controlDict not found in case directory."
    try:
        value = read_entry(control_dict, "application")
    except OpenFOAMError as exc:
        return None, f"Failed to read application: {exc}"
    solver_line = value.strip()
    if not solver_line:
        return None, "application entry is empty."
    solver = solver_line.split()[0].rstrip(";")
    if not solver:
        return None, "Could not determine solver from application entry."
    return solver, None


def validate_initial_fields(case_path: Path) -> list[str]:
    errors: list[str] = []
    zero_dir = case_path / "0"
    zero_orig = case_path / "0.orig"
    if not zero_dir.is_dir():
        if zero_orig.is_dir():
            errors.append("0/ directory missing (only 0.orig present). Copy 0.orig -> 0 first.")
        else:
            errors.append("Missing 0/ initial conditions directory.")
            return errors
    fields = list_field_files(case_path)
    if not fields:
        errors.append("No field files detected in 0/ (or 0.orig).")
        return errors
    required = {"U", "p"}
    missing = sorted(required - set(fields))
    if missing:
        folder_name = "0" if zero_dir.is_dir() else "0.orig"
        errors.append(f"Missing fields in {folder_name}: {', '.join(missing)}")
    return errors


def remove_empty_log(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    try:
        content = log_path.read_text(errors="ignore").strip()
    except OSError:
        return False
    if not content:
        try:
            log_path.unlink()
        except OSError:
            return False
        return True
    return False


def truncate_log(log_path: Path) -> None:
    try:
        log_path.write_text("")
    except OSError:
        return
