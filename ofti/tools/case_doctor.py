from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.boundary import list_field_files
from ofti.core.case import detect_solver
from ofti.core.times import latest_time
from ofti.core.versioning import get_dict_path
from ofti.foam import openfoam
from ofti.foamlib import adapter as foamlib_integration
from ofti.ui_curses.viewer import Viewer


def case_doctor_screen(stdscr: Any, case_path: Path) -> None:
    report = build_case_doctor_report(case_path)
    if not report["errors"] and not report["warnings"]:
        Viewer(stdscr, "\n".join(report["lines"] + ["", "OK: no issues found."])).display()
        return
    lines = report["lines"]
    if report["errors"]:
        lines += ["", "Errors:"] + [f"- {item}" for item in report["errors"]]
    if report["warnings"]:
        lines += ["", "Warnings:"] + [f"- {item}" for item in report["warnings"]]
    Viewer(stdscr, "\n".join(lines)).display()


def build_case_doctor_report(case_path: Path) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    required = _required_dicts()
    _check_required_dicts(case_path, required, errors)
    _check_physics_dicts(case_path, warnings)
    _check_mesh(case_path, errors)
    _check_initial_conditions(case_path, errors, warnings)
    _check_time_dirs(case_path, warnings)

    lint_errors, lint_warnings = _lint_case_dicts(case_path)
    errors.extend(lint_errors)
    warnings.extend(lint_warnings)

    lines = [
        "CASE DOCTOR",
        "",
        f"Path: {case_path}",
        f"Solver: {detect_solver(case_path)}",
        f"Files checked: {len(required)} dicts + 0/ + mesh",
    ]
    return {"lines": lines, "errors": errors, "warnings": warnings}


def _required_dicts() -> list[Path]:
    return [
        get_dict_path("controlDict"),
        get_dict_path("fvSchemes"),
        get_dict_path("fvSolution"),
    ]


def _check_required_dicts(case_path: Path, required: list[Path], errors: list[str]) -> None:
    for rel in required:
        if not (case_path / rel).is_file():
            errors.append(f"Missing {rel}.")


def _check_physics_dicts(case_path: Path, warnings: list[str]) -> None:
    transport = case_path / get_dict_path("transport")
    thermo = case_path / get_dict_path("thermophysical")
    turbulence = case_path / get_dict_path("turbulence")
    if not transport.is_file() and not thermo.is_file():
        warnings.append("Missing constant/transportProperties or thermophysicalProperties.")
    if not turbulence.is_file():
        warnings.append("Missing turbulence properties (turbulenceProperties/RASProperties).")


def _check_mesh(case_path: Path, errors: list[str]) -> None:
    boundary = case_path / "constant" / "polyMesh" / "boundary"
    if not boundary.is_file():
        errors.append("Missing constant/polyMesh/boundary (mesh not generated).")


def _check_initial_conditions(
    case_path: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    zero_dir = case_path / "0"
    zero_orig = case_path / "0.orig"
    if not zero_dir.is_dir() and not zero_orig.is_dir():
        errors.append("Missing 0/ (or 0.orig) initial conditions directory.")
        return
    fields = list_field_files(case_path)
    if not fields:
        warnings.append("No field files detected in 0/ (or 0.orig).")
    missing_fields = sorted({"U", "p"} - set(fields))
    if missing_fields:
        folder_name = zero_dir.name if zero_dir.is_dir() else "0.orig"
        warnings.append(f"Missing fields in {folder_name}: {', '.join(missing_fields)}")
    if not zero_dir.is_dir() and zero_orig.is_dir():
        warnings.append("0/ directory missing (only 0.orig present). Copy 0.orig -> 0.")


def _check_time_dirs(case_path: Path, warnings: list[str]) -> None:
    if latest_time(case_path) in ("", "0", "0.0"):
        warnings.append("No non-zero time directory (case not run yet).")


def _lint_case_dicts(case_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not _can_lint():
        warnings.append("Syntax lint skipped (foamlib not available).")
        return errors, warnings
    try:
        results = openfoam.verify_case(case_path)
    except Exception as exc:
        warnings.append(f"Syntax lint failed: {exc}")
        return errors, warnings
    for path, result in results.items():
        rel = path.relative_to(case_path)
        for err in result.errors:
            errors.append(f"{rel}: {err}")
        for warn in result.warnings:
            warnings.append(f"{rel}: {warn}")
    return errors, warnings


def _can_lint() -> bool:
    return foamlib_integration.available()
