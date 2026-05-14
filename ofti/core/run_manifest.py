from __future__ import annotations

import hashlib
import json
import platform
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ofti.core.case import detect_parallel_settings, detect_solver
from ofti.core.case_snapshot import build_case_snapshot

SCHEMA_VERSION = 1
RECEIPT_KIND = "ofti_run_manifest"
LEGACY_RECEIPT_KIND = "ofti_run_receipt"
SUPPORTED_RECEIPT_KINDS = {RECEIPT_KIND, LEGACY_RECEIPT_KIND}
DEFAULT_INPUT_ROOTS = ("system", "constant", "0")


def build_run_manifest(
    case_path: Path,
    *,
    name: str,
    command: str,
    background: bool,
    detached: bool,
    parallel: int,
    mpi: str | None,
    sync_subdomains: bool,
    prepare_parallel: bool,
    clean_processors: bool,
    extra_env: dict[str, str] | None = None,
    log_path: Path | None = None,
    pid: int | None = None,
    returncode: int | None = None,
    recorded_inputs_copy: bool = False,
    solver_name: str | None = None,
    openfoam_bashrc: Path | None = None,
    openfoam_version: str | None = None,
    build_provenance: dict[str, Any] | None = None,
    source_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case_dir = case_path.expanduser().resolve()
    snapshot = build_case_snapshot(case_dir)
    input_rows = collect_case_inputs(case_dir)
    chosen_solver = solver_name or detect_solver(case_dir)
    build = (
        build_provenance
        if build_provenance is not None
        else _empty_build_provenance(chosen_solver)
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "receipt_kind": RECEIPT_KIND,
        "created_at": _utc_now(),
        "case": {
            "name": case_dir.name,
            "path": str(case_dir),
            "solver": chosen_solver,
            "parallel": detect_parallel_settings(case_dir),
        },
        "launch": {
            "name": name,
            "command": command,
            "background": bool(background),
            "detached": bool(detached),
            "parallel": int(parallel),
            "mpi": mpi,
            "sync_subdomains": bool(sync_subdomains),
            "prepare_parallel": bool(prepare_parallel),
            "clean_processors": bool(clean_processors),
            "extra_env": dict(sorted((extra_env or {}).items())),
            "log_path": str(log_path.resolve()) if log_path is not None else None,
            "pid": pid,
            "returncode": returncode,
        },
        "openfoam": {
            "bashrc": str(openfoam_bashrc.resolve()) if openfoam_bashrc is not None else None,
            "version": openfoam_version or "unknown",
        },
        "build": build,
        "system": {
            "hostname": platform.node() or None,
            "platform": platform.system() or None,
            "kernel": platform.release() or None,
            "arch": platform.machine() or None,
            "python": platform.python_version(),
        },
        "source": source_info if source_info is not None else _empty_source_info(),
        "snapshot": _manifest_snapshot(snapshot),
        "inputs": {
            "roots": list(DEFAULT_INPUT_ROOTS),
            "files": input_rows,
            "tree_hash": _tree_hash(input_rows),
            "mesh_hash": _mesh_hash(input_rows),
            "recorded_inputs_copy": bool(recorded_inputs_copy),
            "inputs_copy_path": None,
        },
    }


def write_run_manifest(
    case_path: Path,
    manifest: dict[str, Any],
    *,
    output: Path | None = None,
    record_inputs_copy: bool = False,
) -> Path:
    case_dir = case_path.expanduser().resolve()
    manifest_path = resolve_manifest_output(case_dir, output)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = deepcopy(manifest)
    payload["inputs"]["recorded_inputs_copy"] = bool(record_inputs_copy)
    if record_inputs_copy:
        inputs_dir = manifest_path.parent / "inputs"
        _copy_input_roots(case_dir, inputs_dir)
        payload["inputs"]["inputs_copy_path"] = "inputs"
    payload["receipt_path"] = str(manifest_path.resolve())
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path.resolve()


def write_case_run_manifest(
    case_path: Path,
    *,
    name: str,
    command: str,
    background: bool,
    detached: bool,
    parallel: int,
    mpi: str | None,
    sync_subdomains: bool,
    prepare_parallel: bool,
    clean_processors: bool,
    extra_env: dict[str, str] | None = None,
    log_path: Path | None = None,
    pid: int | None = None,
    returncode: int | None = None,
    output: Path | None = None,
    record_inputs_copy: bool = False,
    solver_name: str | None = None,
    openfoam_bashrc: Path | None = None,
    openfoam_version: str | None = None,
    build_provenance: dict[str, Any] | None = None,
    source_info: dict[str, Any] | None = None,
) -> Path:
    manifest = build_run_manifest(
        case_path,
        name=name,
        command=command,
        background=background,
        detached=detached,
        parallel=parallel,
        mpi=mpi,
        sync_subdomains=sync_subdomains,
        prepare_parallel=prepare_parallel,
        clean_processors=clean_processors,
        extra_env=extra_env,
        log_path=log_path,
        pid=pid,
        returncode=returncode,
        recorded_inputs_copy=record_inputs_copy,
        solver_name=solver_name,
        openfoam_bashrc=openfoam_bashrc,
        openfoam_version=openfoam_version,
        build_provenance=build_provenance,
        source_info=source_info,
    )
    return write_run_manifest(
        case_path,
        manifest,
        output=output,
        record_inputs_copy=record_inputs_copy,
    )


def load_run_manifest(path: Path) -> dict[str, Any]:
    manifest_path = path.expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"invalid receipt payload: {manifest_path}")
    if payload.get("receipt_kind") not in SUPPORTED_RECEIPT_KINDS:
        raise ValueError(f"unsupported receipt kind: {manifest_path}")
    return payload


def verify_run_manifest(
    manifest_path: Path,
    *,
    case_path: Path | None = None,
    openfoam_version: str | None = None,
    build_provenance_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_manifest = manifest_path.expanduser().resolve()
    manifest = load_run_manifest(resolved_manifest)
    default_case = Path(str(manifest["case"]["path"]))
    target_case = (case_path or default_case).expanduser().resolve()
    if not target_case.is_dir():
        raise ValueError(f"case directory not found: {target_case}")
    expected_rows = list(manifest.get("inputs", {}).get("files", []))
    actual_rows = collect_case_inputs(target_case, roots=_manifest_roots(manifest))
    expected_map = {str(row["path"]): str(row["sha256"]) for row in expected_rows}
    actual_map = {str(row["path"]): str(row["sha256"]) for row in actual_rows}
    missing = sorted(path for path in expected_map if path not in actual_map)
    changed = sorted(
        path
        for path in expected_map
        if path in actual_map and expected_map[path] != actual_map[path]
    )
    extra = sorted(path for path in actual_map if path not in expected_map)
    actual_tree_hash = _tree_hash(actual_rows)
    expected_tree_hash = str(manifest.get("inputs", {}).get("tree_hash") or "")
    actual_version = openfoam_version or "unknown"
    expected_version = str(manifest.get("openfoam", {}).get("version") or "")
    version_match = not expected_version or expected_version in {"unknown", actual_version}
    build_check = (
        build_provenance_check
        if build_provenance_check is not None
        else _unknown_manifest_build_provenance_check(manifest)
    )
    return {
        "receipt": str(resolved_manifest),
        "case": str(target_case),
        "ok": (
            not missing
            and not changed
            and not extra
            and version_match
            and bool(build_check["ok"])
            and actual_tree_hash == expected_tree_hash
        ),
        "missing_files": missing,
        "changed_files": [
            {
                "path": path,
                "expected_sha256": expected_map[path],
                "actual_sha256": actual_map[path],
            }
            for path in changed
        ],
        "extra_files": extra,
        "expected_tree_hash": expected_tree_hash,
        "actual_tree_hash": actual_tree_hash,
        "openfoam": {
            "expected_version": expected_version,
            "actual_version": actual_version,
            "match": version_match,
        },
        "build": build_check,
        "recorded_inputs_copy": bool(manifest.get("inputs", {}).get("recorded_inputs_copy")),
        "restorable": bool(manifest.get("inputs", {}).get("inputs_copy_path")),
    }


def restore_run_manifest(
    manifest_path: Path,
    destination: Path,
    *,
    only: tuple[str, ...] | list[str] | None = None,
    skip: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    resolved_manifest = manifest_path.expanduser().resolve()
    manifest = load_run_manifest(resolved_manifest)
    relative_inputs = manifest.get("inputs", {}).get("inputs_copy_path")
    if not relative_inputs:
        raise ValueError("receipt does not include recorded inputs; restore is not possible")
    inputs_path = resolved_manifest.parent / str(relative_inputs)
    if not inputs_path.is_dir():
        raise ValueError(f"recorded inputs directory not found: {inputs_path}")
    dest = destination.expanduser().resolve()
    if dest.exists():
        if any(dest.iterdir()):
            raise ValueError(f"destination already exists and is not empty: {dest}")
    else:
        dest.mkdir(parents=True, exist_ok=False)
    selected_roots = select_manifest_restore_roots(only=only, skip=skip)
    restored: list[str] = []
    for entry in sorted(inputs_path.iterdir(), key=lambda item: item.name):
        if entry.name not in selected_roots:
            continue
        target = dest / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, symlinks=True)
        else:
            shutil.copy2(entry, target, follow_symlinks=True)
        restored.append(entry.name)
    restored_receipt = dest / ".ofti" / "restored_from_receipt.json"
    restored_receipt.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resolved_manifest, restored_receipt, follow_symlinks=True)
    return {
        "receipt": str(resolved_manifest),
        "destination": str(dest),
        "selected_roots": list(selected_roots),
        "restored": restored,
        "restored_receipt": str(restored_receipt),
        "ok": True,
    }


def collect_case_inputs(
    case_path: Path,
    *,
    roots: tuple[str, ...] | list[str] = DEFAULT_INPUT_ROOTS,
) -> list[dict[str, Any]]:
    case_dir = case_path.expanduser().resolve()
    rows: list[dict[str, Any]] = []
    for root_name in roots:
        root = case_dir / root_name
        if not root.exists():
            continue
        for file_path in _iter_files(root):
            relative = file_path.relative_to(case_dir)
            rows.append(
                {
                    "path": relative.as_posix(),
                    "sha256": _sha256_file(file_path),
                    "size": file_path.stat().st_size,
                },
            )
    rows.sort(key=lambda row: str(row["path"]))
    return rows


def resolve_manifest_output(case_path: Path, output: Path | None) -> Path:
    if output is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        launch_dir = Path.cwd().resolve()
        case_dir = case_path.expanduser().resolve()
        return launch_dir / "runs" / f"{stamp}_{_slug(case_dir.name)}" / "receipt.json"
    destination = output.expanduser()
    if not destination.is_absolute():
        destination = Path.cwd() / destination
    if destination.suffix.lower() == ".json":
        return destination.resolve()
    return (destination / "receipt.json").resolve()


def select_manifest_restore_roots(
    *,
    only: tuple[str, ...] | list[str] | None = None,
    skip: tuple[str, ...] | list[str] | None = None,
) -> tuple[str, ...]:
    selected = list(DEFAULT_INPUT_ROOTS)
    if only:
        selected = _normalize_manifest_roots(only)
    if skip:
        skipped = set(_normalize_manifest_roots(skip))
        selected = [root for root in selected if root not in skipped]
    if not selected:
        raise ValueError("receipt restore selection is empty; nothing to restore")
    return tuple(selected)


def _copy_input_roots(case_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    case_dir = case_path.expanduser().resolve()
    for root_name in DEFAULT_INPUT_ROOTS:
        source = case_dir / root_name
        if not source.exists():
            continue
        target = destination / root_name
        if source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=True)


def _empty_build_provenance(solver_name: str | None) -> dict[str, Any]:
    return {
        "solver": {"name": solver_name, "path": None, "sha256": None, "size": None},
        "linked_libs": {"count": 0, "hash": None, "files": [], "missing": []},
        "compiler": {
            "compiler": None,
            "compiler_type": None,
            "compile_option": None,
            "cc": None,
            "cxx": None,
            "cflags": None,
            "cxxflags": None,
            "ldflags": None,
        },
        "openfoam_env": {},
    }


def _unknown_manifest_build_provenance_check(manifest: dict[str, Any]) -> dict[str, Any]:
    expected = manifest.get("build", {})
    solver = expected.get("solver", {}) if isinstance(expected, dict) else {}
    libs = expected.get("linked_libs", {}) if isinstance(expected, dict) else {}
    return {
        "ok": True,
        "solver": {
            "expected_sha256": solver.get("sha256"),
            "actual_sha256": None,
            "match": True,
            "path": solver.get("path"),
        },
        "linked_libs": {
            "expected_hash": libs.get("hash"),
            "actual_hash": None,
            "match": True,
            "count": libs.get("count", 0),
            "missing": libs.get("missing", []),
        },
    }


def _empty_source_info() -> dict[str, Any]:
    return {"git_root": None, "git_sha": None, "git_dirty": False, "git_dirty_files": []}

def _iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    rows: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rows.append(path)
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hash(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _mesh_hash(rows: list[dict[str, Any]]) -> str | None:
    mesh_rows = [row for row in rows if str(row["path"]).startswith("constant/polyMesh/")]
    if not mesh_rows:
        return None
    return _tree_hash(mesh_rows)


def _manifest_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    mesh = dict(snapshot.get("mesh", {}))
    boundary = dict(mesh.get("boundary", {}))
    return {
        "latest_time": snapshot.get("case", {}).get("latest_time"),
        "log": snapshot.get("case", {}).get("log"),
        "mesh": {
            "cells": mesh.get("cells"),
            "faces": mesh.get("faces"),
            "points": mesh.get("points"),
            "patches": boundary.get("patches"),
            "zones": boundary.get("zones"),
        },
        "fields": sorted(snapshot.get("fields", {}).keys()),
    }


def _manifest_roots(manifest: dict[str, Any]) -> tuple[str, ...]:
    roots = manifest.get("inputs", {}).get("roots", DEFAULT_INPUT_ROOTS)
    if not isinstance(roots, list):
        return DEFAULT_INPUT_ROOTS
    cleaned = [str(item) for item in roots if str(item).strip()]
    return tuple(cleaned) if cleaned else DEFAULT_INPUT_ROOTS


def _normalize_manifest_roots(values: tuple[str, ...] | list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for token in str(raw).split(","):
            name = token.strip()
            if not name:
                continue
            if name not in DEFAULT_INPUT_ROOTS:
                expected = ", ".join(DEFAULT_INPUT_ROOTS)
                raise ValueError(f"invalid receipt root '{name}' (expected one of: {expected})")
            if name in seen:
                continue
            cleaned.append(name)
            seen.add(name)
    return cleaned


def _slug(value: str) -> str:
    token = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    while "__" in token:
        token = token.replace("__", "_")
    return token.strip("_") or "case"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
