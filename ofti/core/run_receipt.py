from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ofti.core.case import detect_parallel_settings, detect_solver
from ofti.core.case_snapshot import build_case_snapshot
from ofti.foam.openfoam_env import detect_openfoam_version, resolve_openfoam_bashrc
from ofti.foam.subprocess_utils import resolve_executable, run_trusted

SCHEMA_VERSION = 1
RECEIPT_KIND = "ofti_run_receipt"
DEFAULT_INPUT_ROOTS = ("system", "constant", "0")
_OF_ENV_KEYS = (
    "WM_PROJECT",
    "WM_PROJECT_DIR",
    "WM_PROJECT_VERSION",
    "FOAM_API",
    "WM_OPTIONS",
    "WM_COMPILER",
    "WM_COMPILER_TYPE",
    "WM_COMPILE_OPTION",
    "WM_LABEL_SIZE",
    "WM_PRECISION_OPTION",
    "WM_CC",
    "WM_CXX",
    "WM_CFLAGS",
    "WM_CXXFLAGS",
    "WM_LDFLAGS",
    "FOAM_APPBIN",
    "FOAM_LIBBIN",
    "FOAM_SITE_APPBIN",
    "FOAM_SITE_LIBBIN",
    "FOAM_USER_APPBIN",
    "FOAM_USER_LIBBIN",
)


def build_run_receipt(
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
) -> dict[str, Any]:
    case_dir = case_path.expanduser().resolve()
    bashrc = resolve_openfoam_bashrc()
    snapshot = build_case_snapshot(case_dir)
    input_rows = collect_case_inputs(case_dir)
    chosen_solver = solver_name or detect_solver(case_dir)
    build = _build_provenance(chosen_solver, bashrc=bashrc)
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
            "bashrc": str(bashrc.resolve()) if bashrc is not None else None,
            "version": detect_openfoam_version(),
        },
        "build": build,
        "system": {
            "hostname": platform.node() or None,
            "platform": platform.system() or None,
            "kernel": platform.release() or None,
            "arch": platform.machine() or None,
            "python": platform.python_version(),
        },
        "source": _git_info(case_dir),
        "snapshot": _receipt_snapshot(snapshot),
        "inputs": {
            "roots": list(DEFAULT_INPUT_ROOTS),
            "files": input_rows,
            "tree_hash": _tree_hash(input_rows),
            "mesh_hash": _mesh_hash(input_rows),
            "recorded_inputs_copy": bool(recorded_inputs_copy),
            "inputs_copy_path": None,
        },
    }


def write_run_receipt(
    case_path: Path,
    receipt: dict[str, Any],
    *,
    output: Path | None = None,
    record_inputs_copy: bool = False,
) -> Path:
    case_dir = case_path.expanduser().resolve()
    receipt_path = resolve_receipt_output(case_dir, output)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    payload = deepcopy(receipt)
    payload["inputs"]["recorded_inputs_copy"] = bool(record_inputs_copy)
    if record_inputs_copy:
        inputs_dir = receipt_path.parent / "inputs"
        _copy_input_roots(case_dir, inputs_dir)
        payload["inputs"]["inputs_copy_path"] = "inputs"
    payload["receipt_path"] = str(receipt_path.resolve())
    receipt_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return receipt_path.resolve()


def write_case_run_receipt(
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
) -> Path:
    receipt = build_run_receipt(
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
    )
    return write_run_receipt(
        case_path,
        receipt,
        output=output,
        record_inputs_copy=record_inputs_copy,
    )


def load_run_receipt(path: Path) -> dict[str, Any]:
    receipt_path = path.expanduser().resolve()
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"invalid receipt payload: {receipt_path}")
    if payload.get("receipt_kind") != RECEIPT_KIND:
        raise ValueError(f"unsupported receipt kind: {receipt_path}")
    return payload


def verify_run_receipt(receipt_path: Path, *, case_path: Path | None = None) -> dict[str, Any]:
    resolved_receipt = receipt_path.expanduser().resolve()
    receipt = load_run_receipt(resolved_receipt)
    default_case = Path(str(receipt["case"]["path"]))
    target_case = (case_path or default_case).expanduser().resolve()
    if not target_case.is_dir():
        raise ValueError(f"case directory not found: {target_case}")
    expected_rows = list(receipt.get("inputs", {}).get("files", []))
    actual_rows = collect_case_inputs(target_case, roots=_receipt_roots(receipt))
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
    expected_tree_hash = str(receipt.get("inputs", {}).get("tree_hash") or "")
    actual_version = detect_openfoam_version()
    expected_version = str(receipt.get("openfoam", {}).get("version") or "")
    version_match = not expected_version or expected_version in {"unknown", actual_version}
    build_check = _verify_build_provenance(receipt)
    return {
        "receipt": str(resolved_receipt),
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
        "recorded_inputs_copy": bool(receipt.get("inputs", {}).get("recorded_inputs_copy")),
        "restorable": bool(receipt.get("inputs", {}).get("inputs_copy_path")),
    }


def restore_run_receipt(
    receipt_path: Path,
    destination: Path,
    *,
    only: tuple[str, ...] | list[str] | None = None,
    skip: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    resolved_receipt = receipt_path.expanduser().resolve()
    receipt = load_run_receipt(resolved_receipt)
    relative_inputs = receipt.get("inputs", {}).get("inputs_copy_path")
    if not relative_inputs:
        raise ValueError("receipt does not include recorded inputs; restore is not possible")
    inputs_path = resolved_receipt.parent / str(relative_inputs)
    if not inputs_path.is_dir():
        raise ValueError(f"recorded inputs directory not found: {inputs_path}")
    dest = destination.expanduser().resolve()
    if dest.exists():
        if any(dest.iterdir()):
            raise ValueError(f"destination already exists and is not empty: {dest}")
    else:
        dest.mkdir(parents=True, exist_ok=False)
    selected_roots = select_receipt_restore_roots(only=only, skip=skip)
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
    shutil.copy2(resolved_receipt, restored_receipt, follow_symlinks=True)
    return {
        "receipt": str(resolved_receipt),
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


def resolve_receipt_output(case_path: Path, output: Path | None) -> Path:
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


def select_receipt_restore_roots(
    *,
    only: tuple[str, ...] | list[str] | None = None,
    skip: tuple[str, ...] | list[str] | None = None,
) -> tuple[str, ...]:
    selected = list(DEFAULT_INPUT_ROOTS)
    if only:
        selected = _normalize_receipt_roots(only)
    if skip:
        skipped = set(_normalize_receipt_roots(skip))
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


def _build_provenance(solver_name: str | None, *, bashrc: Path | None) -> dict[str, Any]:
    env = _effective_openfoam_env(bashrc)
    solver_binary = _solver_binary_row(solver_name, bashrc=bashrc)
    linked_libs = _linked_library_rows(solver_binary.get("path"))
    return {
        "solver": solver_binary,
        "linked_libs": linked_libs,
        "compiler": {
            "compiler": env.get("WM_COMPILER"),
            "compiler_type": env.get("WM_COMPILER_TYPE"),
            "compile_option": env.get("WM_COMPILE_OPTION"),
            "cc": env.get("WM_CC"),
            "cxx": env.get("WM_CXX"),
            "cflags": env.get("WM_CFLAGS"),
            "cxxflags": env.get("WM_CXXFLAGS"),
            "ldflags": env.get("WM_LDFLAGS"),
        },
        "openfoam_env": dict(sorted(env.items())),
    }


def _verify_build_provenance(receipt: dict[str, Any]) -> dict[str, Any]:
    expected = receipt.get("build", {})
    solver = expected.get("solver", {})
    solver_name = (
        str(solver.get("name") or receipt.get("case", {}).get("solver") or "").strip() or None
    )
    bashrc_value = receipt.get("openfoam", {}).get("bashrc")
    bashrc = Path(str(bashrc_value)).expanduser() if bashrc_value else resolve_openfoam_bashrc()
    actual_solver = _solver_binary_row(solver_name, bashrc=bashrc)
    expected_solver_hash = str(solver.get("sha256") or "")
    actual_solver_hash = str(actual_solver.get("sha256") or "")
    solver_match = not expected_solver_hash or expected_solver_hash == actual_solver_hash
    expected_libs = expected.get("linked_libs", {})
    actual_libs = _linked_library_rows(actual_solver.get("path"))
    expected_lib_hash = str(expected_libs.get("hash") or "")
    actual_lib_hash = str(actual_libs.get("hash") or "")
    libs_match = not expected_lib_hash or expected_lib_hash == actual_lib_hash
    return {
        "ok": bool(solver_match and libs_match),
        "solver": {
            "expected_sha256": expected_solver_hash or None,
            "actual_sha256": actual_solver_hash or None,
            "match": solver_match,
            "path": actual_solver.get("path"),
        },
        "linked_libs": {
            "expected_hash": expected_lib_hash or None,
            "actual_hash": actual_lib_hash or None,
            "match": libs_match,
            "count": actual_libs.get("count"),
            "missing": actual_libs.get("missing", []),
        },
    }


def _effective_openfoam_env(bashrc: Path | None) -> dict[str, str]:
    if bashrc is None:
        return _selected_env(os.environ)
    shell = f'. {shlex.quote(str(bashrc))}; env'
    try:
        result = run_trusted(
            ["/bin/bash", "--noprofile", "--norc", "-c", shell],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return _selected_env(os.environ)
    if result.returncode != 0:
        return _selected_env(os.environ)
    return _selected_env(_parse_env_lines(result.stdout))


def _parse_env_lines(text: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        payload[key] = value
    return payload


def _selected_env(env: Any) -> dict[str, str]:
    return {key: str(env[key]) for key in _OF_ENV_KEYS if key in env and str(env[key]).strip()}


def _solver_binary_row(solver_name: str | None, *, bashrc: Path | None) -> dict[str, Any]:
    if not solver_name:
        return {"name": None, "path": None, "sha256": None, "size": None}
    path = _resolve_solver_binary_path(solver_name, bashrc=bashrc)
    if path is None:
        return {"name": solver_name, "path": None, "sha256": None, "size": None}
    return {
        "name": solver_name,
        "path": str(path),
        "sha256": _sha256_file(path),
        "size": path.stat().st_size,
    }


def _resolve_solver_binary_path(solver_name: str, *, bashrc: Path | None) -> Path | None:
    try:
        return Path(resolve_executable(solver_name)).resolve()
    except (FileNotFoundError, OSError):
        pass
    if bashrc is None:
        return None
    shell = f'. {shlex.quote(str(bashrc))}; command -v {shlex.quote(solver_name)}'
    try:
        result = run_trusted(
            ["/bin/bash", "--noprofile", "--norc", "-c", shell],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    resolved = result.stdout.strip()
    if not resolved:
        return None
    path = Path(resolved).expanduser()
    return path.resolve() if path.exists() else None


def _linked_library_rows(binary_path_value: Any) -> dict[str, Any]:
    if not binary_path_value:
        return {"count": 0, "hash": None, "files": [], "missing": []}
    binary_path = Path(str(binary_path_value))
    try:
        result = run_trusted(
            ["ldd", str(binary_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return {"count": 0, "hash": None, "files": [], "missing": []}
    if result.returncode != 0:
        return {"count": 0, "hash": None, "files": [], "missing": []}
    files: list[dict[str, Any]] = []
    missing: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        row = line.strip()
        if not row:
            continue
        resolved = _ldd_resolved_path(row)
        if resolved == "missing":
            missing.append(row)
            continue
        if resolved is None:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        path = Path(resolved)
        if not path.is_file():
            continue
        files.append(
            {
                "path": str(path),
                "sha256": _sha256_file(path),
                "size": path.stat().st_size,
            },
        )
    files.sort(key=lambda row: str(row["path"]))
    return {
        "count": len(files),
        "hash": _tree_hash(files) if files else None,
        "files": files,
        "missing": missing,
    }


def _ldd_resolved_path(line: str) -> str | None:
    if "=>" in line:
        _, right = line.split("=>", 1)
        trimmed = right.strip()
        if trimmed.startswith("not found"):
            return "missing"
        path = trimmed.split(" ", 1)[0]
        return path if path.startswith("/") else None
    token = line.split(" ", 1)[0].strip()
    return token if token.startswith("/") else None


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


def _receipt_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
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


def _git_info(case_path: Path) -> dict[str, Any]:
    root = _git_capture(case_path, "rev-parse", "--show-toplevel")
    sha = _git_capture(case_path, "rev-parse", "HEAD")
    status = _git_capture(case_path, "status", "--porcelain")
    dirty_files = []
    dirty = False
    if status["ok"] and status["stdout"]:
        dirty = True
        for line in str(status["stdout"]).splitlines():
            token = line[3:].strip() if len(line) > 3 else line.strip()
            if token:
                dirty_files.append(token)
    return {
        "git_root": root["stdout"] if root["ok"] else None,
        "git_sha": sha["stdout"] if sha["ok"] else None,
        "git_dirty": dirty,
        "git_dirty_files": dirty_files,
    }


def _git_capture(case_path: Path, *args: str) -> dict[str, Any]:
    try:
        result = run_trusted(
            ["git", "-C", str(case_path), *args],
            check=False,
            capture_output=True,
            text=True,
            env=_git_env(),
        )
    except (OSError, FileNotFoundError):
        return {"ok": False, "stdout": "", "stderr": ""}
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return env


def _receipt_roots(receipt: dict[str, Any]) -> tuple[str, ...]:
    roots = receipt.get("inputs", {}).get("roots", DEFAULT_INPUT_ROOTS)
    if not isinstance(roots, list):
        return DEFAULT_INPUT_ROOTS
    cleaned = [str(item) for item in roots if str(item).strip()]
    return tuple(cleaned) if cleaned else DEFAULT_INPUT_ROOTS


def _normalize_receipt_roots(values: tuple[str, ...] | list[str]) -> list[str]:
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
