from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ofti.core.entry_io import list_subkeys, read_entry
from ofti.foam.openfoam import OpenFOAMError
from ofti.foamlib import adapter as foamlib_integration


@dataclass
class BoundaryCell:
    status: str
    bc_type: str
    value: str


@dataclass
class BoundaryMatrix:
    fields: list[str]
    patches: list[str]
    patch_types: dict[str, str]
    data: dict[str, dict[str, BoundaryCell]]


def build_boundary_matrix(case_path: Path) -> BoundaryMatrix:
    patches, patch_types = parse_boundary_file(case_path / "constant" / "polyMesh" / "boundary")
    fields = list_field_files(case_path)
    data: dict[str, dict[str, BoundaryCell]] = {patch: {} for patch in patches}

    for field in fields:
        file_path = zero_dir(case_path) / field
        try:
            subkeys = list_subkeys(file_path, "boundaryField")
        except OpenFOAMError:
            subkeys = []
        wildcard_keys = [key for key in subkeys if key not in patches]
        wildcard_key = ".*" if ".*" in subkeys else (wildcard_keys[0] if wildcard_keys else None)
        for patch in patches:
            if patch in subkeys:
                bc_type = read_optional(file_path, f"boundaryField.{patch}.type")
                bc_value = read_optional(file_path, f"boundaryField.{patch}.value")
                data[patch][field] = BoundaryCell("OK", bc_type or "unknown", bc_value or "")
            elif wildcard_key:
                type_key = f"boundaryField.{wildcard_key}.type"
                value_key = f"boundaryField.{wildcard_key}.value"
                bc_type = read_optional(file_path, type_key)
                bc_value = read_optional(file_path, value_key)
                data[patch][field] = BoundaryCell(
                    "WILDCARD",
                    bc_type or "wildcard",
                    bc_value or "Inherited",
                )
            else:
                data[patch][field] = BoundaryCell("MISSING", "missing", "")

    return BoundaryMatrix(fields=fields, patches=patches, patch_types=patch_types, data=data)


def zero_dir(case_path: Path) -> Path:
    zero = case_path / "0"
    if zero.is_dir():
        return zero
    zero_orig = case_path / "0.orig"
    if zero_orig.is_dir():
        return zero_orig
    return zero


def list_field_files(case_path: Path) -> list[str]:
    folder = zero_dir(case_path)
    if not folder.is_dir():
        return []
    fields: list[str] = []
    try:
        for entry in os.scandir(folder):
            if not entry.is_file():
                continue
            if entry.name.startswith(".") or entry.name.endswith("~"):
                continue
            fields.append(entry.name)
    except OSError:
        return []
    return sorted(fields)


def read_optional(file_path: Path, key: str) -> str | None:
    try:
        value = read_entry(file_path, key)
    except OpenFOAMError:
        return None
    return value.strip().strip(";")


def parse_boundary_file(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.is_file():
        return [], {}
    if foamlib_integration.available():
        try:
            return foamlib_integration.parse_boundary_file(path)
        except Exception as exc:
            logging.debug("foamlib boundary parse failed: %s", exc)
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return [], {}
    return parse_boundary_text(text)


def rename_boundary_patch(case_path: Path, old: str, new: str) -> tuple[bool, str]:
    if old == new:
        return False, "New patch name matches the existing name."
    boundary_path = case_path / "constant" / "polyMesh" / "boundary"
    if not boundary_path.is_file():
        return False, "Boundary file not found."
    if not foamlib_integration.available():
        return False, "Rename requires foamlib."
    try:
        ok = foamlib_integration.rename_boundary_patch(boundary_path, old, new)
    except Exception as exc:
        return False, f"Failed to rename patch: {exc}"
    if not ok:
        return False, "Patch not found in boundary file."
    for field in list_field_files(case_path):
        file_path = zero_dir(case_path) / field
        try:
            foamlib_integration.rename_boundary_field_patch(file_path, old, new)
        except Exception:
            continue
    return True, ""


def change_patch_type(case_path: Path, patch: str, new_type: str) -> tuple[bool, str]:
    boundary_path = case_path / "constant" / "polyMesh" / "boundary"
    if not boundary_path.is_file():
        return False, "Boundary file not found."
    if not foamlib_integration.available():
        return False, "Patch type update requires foamlib."
    try:
        ok = foamlib_integration.change_boundary_patch_type(boundary_path, patch, new_type)
    except Exception as exc:
        return False, f"Failed to update patch type: {exc}"
    if not ok:
        return False, "Patch not found in boundary file."
    return True, ""


@dataclass
class _BoundaryParseState:
    in_entries: bool = False
    current_patch: str | None = None
    brace_depth: int = 0
    pending_patch: str | None = None


def parse_boundary_text(text: str) -> tuple[list[str], dict[str, str]]:  # noqa: C901
    patches: list[str] = []
    patch_types: dict[str, str] = {}
    state = _BoundaryParseState()

    for raw in text.splitlines():
        line = strip_comments(raw).strip()
        if not line or line.startswith("FoamFile"):
            continue
        if not state.in_entries:
            if line == "(" or line.endswith("("):
                state.in_entries = True
            continue
        if line.startswith(")"):
            break

        if state.current_patch is None:
            if state.pending_patch and line.startswith("{"):
                state.current_patch = state.pending_patch
                state.pending_patch = None
                patches.append(state.current_patch)
                state.brace_depth = 1
                continue
            name = match_patch_start(line)
            if name:
                state.current_patch = name
                patches.append(name)
                state.brace_depth = 1
                continue
            if looks_like_patch_name(line):
                state.pending_patch = line
            continue

        update_patch_type(line, state.current_patch, patch_types)
        update_brace_depth(line, state)
        if state.brace_depth <= 0:
            state.current_patch = None
            state.brace_depth = 0

    return patches, patch_types


def match_patch_start(line: str) -> str | None:
    match = re.match(r"^([A-Za-z0-9_./-]+)\s*\{", line)
    return match.group(1) if match else None


def looks_like_patch_name(line: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_./-]+$", line))


def update_patch_type(line: str, patch: str, patch_types: dict[str, str]) -> None:
    if "type" not in line or ";" not in line:
        return
    parts = line.replace(";", " ").split()
    if len(parts) >= 2 and parts[0] == "type":
        patch_types[patch] = parts[1]


def update_brace_depth(line: str, state: _BoundaryParseState) -> None:
    state.brace_depth += line.count("{")
    state.brace_depth -= line.count("}")


def strip_comments(line: str) -> str:
    if "//" in line:
        return line.split("//", 1)[0]
    return line
