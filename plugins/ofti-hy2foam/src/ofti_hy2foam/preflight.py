from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ofti.core.field_io import resolve_time_dir
from ofti.core.output_contract import command_name, stamp_payload

from .field_boundaries import field_boundary_patches, mesh_patch_names
from .physical import AIR11_SPECIES

REQUIRED_FIELDS = ("Tt", "Tv", "p", "U")


class Hy2FoamPreflightCommand:
    name = "hy2foam-preflight"

    def add_parser(self, subparsers) -> None:
        parser = subparsers.add_parser("hy2foam-preflight", help="Run hy2Foam-specific preflight")
        parser.add_argument("case_dir", type=Path)
        parser.add_argument("--time", default="latest")
        parser.add_argument("--json", action="store_true")
        parser.set_defaults(func=self.run)

    def run(self, args) -> int:
        payload = preflight_payload(args.case_dir, time_name=str(getattr(args, "time", "latest")))
        if bool(getattr(args, "json", False)):
            print(json.dumps(stamp_payload(payload, command_name(args)), indent=2, sort_keys=True))
            return 0 if payload["ok"] else 1
        print(f"case={payload['case']}")
        print(f"ok={payload['ok']}")
        for check in payload["checks"]:
            print(f"{check['name']}={check['status']} {check['detail']}")
        return 0 if payload["ok"] else 1


def preflight_payload(case_dir: Path, *, time_name: str = "latest") -> dict[str, Any]:
    checks = [
        _openfoam_version_check(),
        _hystrath_libs_check(case_dir),
        _required_fields_check(case_dir, time_name=time_name),
        _species_patch_consistency_check(case_dir, time_name=time_name),
        _species_order_consistency_check(case_dir),
        _turbulence_consistency_check(case_dir),
        _duplicate_function_objects_check(case_dir),
    ]
    return {
        "case": str(case_dir),
        "ok": all(check["status"] != "FAIL" for check in checks),
        "checks": checks,
    }


def _openfoam_version_check() -> dict[str, str]:
    version = os.environ.get("WM_PROJECT_VERSION", "")
    if not version:
        return _check("openfoam_version", "WARN", "WM_PROJECT_VERSION is not set")
    if version == "v2512" or version.endswith("2512"):
        return _check("openfoam_version", "PASS", version)
    return _check("openfoam_version", "WARN", f"expected v2512 profile, got {version}")


def _hystrath_libs_check(case_dir: Path) -> dict[str, str]:
    text = _read(case_dir / "system" / "controlDict")
    if "hyStrath" in text or "hy2Foam" in text:
        return _check("hystrath_libs", "PASS", "hyStrath/hy2Foam marker found")
    return _check("hystrath_libs", "WARN", "no hyStrath/hy2Foam marker found in controlDict")


def _required_fields_check(case_dir: Path, *, time_name: str) -> dict[str, str]:
    try:
        time_dir = resolve_time_dir(case_dir, time_name)
    except ValueError as exc:
        return _check("required_fields", "FAIL", str(exc))
    missing = [name for name in REQUIRED_FIELDS if not (time_dir / name).is_file()]
    if missing:
        return _check("required_fields", "FAIL", "missing " + ",".join(missing))
    return _check("required_fields", "PASS", f"{time_dir.name}: {','.join(REQUIRED_FIELDS)}")


def _duplicate_function_objects_check(case_dir: Path) -> dict[str, str]:
    text = _read(case_dir / "system" / "controlDict")
    functions = _named_block(text, "functions")
    if not functions:
        return _check("duplicate_function_objects", "PASS", "no functions block")
    names = [match.group(1) for match in re.finditer(r"\b([A-Za-z0-9_+.-]+)\s*\{", functions)]
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        return _check("duplicate_function_objects", "FAIL", ",".join(duplicates))
    return _check("duplicate_function_objects", "PASS", f"{len(names)} function objects")


def _species_patch_consistency_check(case_dir: Path, *, time_name: str) -> dict[str, str]:
    try:
        time_dir = resolve_time_dir(case_dir, time_name)
    except ValueError as exc:
        return _check("species_patch_consistency", "FAIL", str(exc))
    species = [name for name in AIR11_SPECIES if (time_dir / name).is_file()]
    if not species:
        return _check("species_patch_consistency", "WARN", "no species fields found")
    expected = mesh_patch_names(case_dir)
    if not expected:
        first = field_boundary_patches(time_dir / species[0])
        expected = {item["patch"] for item in first}
    mismatches: list[str] = []
    for name in species:
        patches = {item["patch"] for item in field_boundary_patches(time_dir / name)}
        if patches != expected:
            missing = sorted(expected - patches)
            extra = sorted(patches - expected)
            mismatches.append(f"{name}:missing={','.join(missing)} extra={','.join(extra)}")
    if mismatches:
        return _check("species_patch_consistency", "FAIL", "; ".join(mismatches))
    return _check("species_patch_consistency", "PASS", f"{len(species)} species fields")


def _species_order_consistency_check(case_dir: Path) -> dict[str, str]:
    orders = _species_orders(case_dir)
    if len(orders) < 2:
        return _check("species_order_consistency", "WARN", "fewer than two species-order sources")
    reference = orders[0][2]
    mismatches = [
        f"{path}:{key}"
        for path, key, values in orders[1:]
        if values != reference
    ]
    if mismatches:
        first_path, first_key, _values = orders[0]
        return _check(
            "species_order_consistency",
            "FAIL",
            f"reference={first_path}:{first_key}; mismatches={','.join(mismatches)}",
        )
    return _check("species_order_consistency", "PASS", f"{len(orders)} sources")


def _turbulence_consistency_check(case_dir: Path) -> dict[str, str]:
    path = case_dir / "constant" / "turbulenceProperties"
    if not path.is_file():
        return _check("turbulence_consistency", "WARN", "constant/turbulenceProperties missing")
    text = _read(path)
    match = re.search(r"\bsimulationType\s+([^;]+);", text)
    if not match:
        return _check("turbulence_consistency", "FAIL", "simulationType missing")
    simulation_type = match.group(1).strip()
    status = "PASS"
    detail = simulation_type
    if simulation_type == "laminar":
        if (case_dir / "constant" / "RASProperties").exists():
            status = "WARN"
            detail = "laminar with RASProperties present"
    elif simulation_type == "RAS" and not (case_dir / "constant" / "RASProperties").is_file():
        status = "FAIL"
        detail = "RAS selected but RASProperties missing"
    elif simulation_type == "LES" and not (case_dir / "constant" / "LESProperties").is_file():
        status = "FAIL"
        detail = "LES selected but LESProperties missing"
    elif simulation_type not in {"RAS", "LES"}:
        status = "WARN"
        detail = f"unknown simulationType {simulation_type}"
    return _check("turbulence_consistency", status, detail)


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""


def _species_orders(case_dir: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    roots = [case_dir / "constant", case_dir / "system"]
    orders: list[tuple[str, str, tuple[str, ...]]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            text = _read(path)
            for key, values in _species_order_entries(text):
                rel = str(path.relative_to(case_dir))
                orders.append((rel, key, values))
    return orders


def _species_order_entries(text: str) -> list[tuple[str, tuple[str, ...]]]:
    entries: list[tuple[str, tuple[str, ...]]] = []
    keys = r"(?:species|speciesOrder|stateInputOrder|inputOrder|outputOrder)"
    for match in re.finditer(rf"\b(?P<key>{keys})\s*\((?P<body>[^)]*)\)\s*;", text, re.DOTALL):
        species = _recognized_species(match.group("body"))
        if len(species) >= 2:
            entries.append((match.group("key"), species))
    return entries


def _recognized_species(text: str) -> tuple[str, ...]:
    names = re.findall(r"[A-Za-z0-9_+-]+", text)
    return tuple(name for name in names if name in AIR11_SPECIES)


def _named_block(text: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*\{{", text)
    if not match:
        return ""
    start = match.end()
    depth = 1
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index]
    return ""
