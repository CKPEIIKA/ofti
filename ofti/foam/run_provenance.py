from __future__ import annotations

import hashlib
import os
import shlex
from pathlib import Path
from typing import Any

from ofti.foam.openfoam_env import resolve_openfoam_bashrc
from ofti.foam.subprocess_utils import resolve_executable, run_trusted

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


def build_provenance(solver_name: str | None, *, bashrc: Path | None) -> dict[str, Any]:
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


def verify_build_provenance(receipt: dict[str, Any]) -> dict[str, Any]:
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
    shell = f". {shlex.quote(str(bashrc))}; env"
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
    shell = f". {shlex.quote(str(bashrc))}; command -v {shlex.quote(solver_name)}"
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


def git_info(case_path: Path) -> dict[str, Any]:
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

