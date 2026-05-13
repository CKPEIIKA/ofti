from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ofti.core.case import read_number_of_subdomains
from ofti.tools.case_doctor import build_case_doctor_report
from ofti.tools.resource_watch_service import resource_watch_payload


def lint_payload(case_path: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    _add_doctor_findings(findings, case_path)
    _add_pressure_reference_findings(findings, case_path)
    _add_decomposition_findings(findings, case_path)
    _add_resource_findings(findings, case_path)
    return {
        "case": str(case_path),
        "errors": sum(1 for row in findings if row["severity"] == "ERROR"),
        "warnings": sum(1 for row in findings if row["severity"] == "WARN"),
        "info": sum(1 for row in findings if row["severity"] == "INFO"),
        "findings": findings,
    }


def lint_exit_code(payload: dict[str, Any]) -> int:
    return 1 if int(payload.get("errors") or 0) else 0


def _add_doctor_findings(findings: list[dict[str, str]], case_path: Path) -> None:
    report = build_case_doctor_report(case_path)
    for message in report["errors"]:
        findings.append(
            _finding(
                "ERROR",
                "doctor",
                message,
                "case doctor",
                "Fix the reported case prerequisite.",
            ),
        )
    for message in report["warnings"]:
        findings.append(
            _finding(
                "WARN",
                "doctor",
                message,
                "case doctor",
                "Review before launch.",
            ),
        )


def _add_pressure_reference_findings(findings: list[dict[str, str]], case_path: Path) -> None:
    p_file = _initial_field_path(case_path, "p")
    fv_solution = case_path / "system" / "fvSolution"
    if p_file is None or not fv_solution.is_file():
        return
    try:
        p_text = p_file.read_text(errors="ignore")
        solution_text = fv_solution.read_text(errors="ignore")
    except OSError:
        return
    has_fixed_p = "fixedValue" in p_text
    has_ref = "pRefCell" in solution_text and "pRefValue" in solution_text
    if not has_fixed_p and not has_ref:
        findings.append(
            _finding(
                "WARN",
                "pressure-reference",
                "No fixedValue p boundary and no pRefCell/pRefValue found.",
                "0/p and system/fvSolution",
                "Add a pressure reference for closed incompressible cases.",
            ),
        )


def _add_decomposition_findings(findings: list[dict[str, str]], case_path: Path) -> None:
    processors = _processor_dirs(case_path)
    decompose_dict = case_path / "system" / "decomposeParDict"
    if processors and not decompose_dict.is_file():
        findings.append(
            _finding(
                "WARN",
                "decomposition",
                "processor* directories exist but system/decomposeParDict is missing.",
                "case root",
                "Recreate decomposeParDict or remove stale processor directories.",
            ),
        )
        return
    if not processors or not decompose_dict.is_file():
        return
    expected = read_number_of_subdomains(decompose_dict)
    if expected is None:
        expected = _read_subdomains_fallback(decompose_dict)
    if expected is None:
        findings.append(
            _finding(
                "WARN",
                "decomposition",
                "numberOfSubdomains is missing or invalid.",
                "system/decomposeParDict",
                "Set numberOfSubdomains to match intended MPI ranks.",
            ),
        )
        return
    if expected != len(processors):
        findings.append(
            _finding(
                "WARN",
                "decomposition",
                f"numberOfSubdomains={expected} but processor dirs={len(processors)}.",
                "system/decomposeParDict and processor*",
                "Re-run decomposePar or update numberOfSubdomains.",
            ),
        )


def _add_resource_findings(findings: list[dict[str, str]], case_path: Path) -> None:
    payload = resource_watch_payload(case_path)
    risk = str(payload.get("risk") or "")
    if risk and risk != "low":
        findings.append(
            _finding(
                "WARN",
                "resource-watch",
                risk,
                "system/controlDict and runtime artifacts",
                "; ".join(payload.get("suggestions", [])) or "Review resource settings.",
            ),
        )


def _finding(
    severity: str,
    rule: str,
    message: str,
    evidence: str,
    advice: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "rule": rule,
        "message": message,
        "evidence": evidence,
        "advice": advice,
    }


def _initial_field_path(case_path: Path, field: str) -> Path | None:
    for dirname in ("0", "0.orig"):
        path = case_path / dirname / field
        if path.is_file():
            return path
    return None


def _processor_dirs(case_path: Path) -> list[Path]:
    try:
        return sorted(
            entry
            for entry in case_path.iterdir()
            if entry.is_dir() and re.fullmatch(r"processor\d+", entry.name)
        )
    except OSError:
        return []


def _read_subdomains_fallback(path: Path) -> int | None:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return None
    match = re.search(r"(?m)^\s*numberOfSubdomains\s+([0-9]+)\s*;", text)
    return int(match.group(1)) if match else None
