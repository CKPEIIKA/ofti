from __future__ import annotations

import inspect
import os
import sys
import ast
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from ofti.core.boundary import build_boundary_matrix
from ofti.foam import openfoam
from ofti.foamlib_adapter import available as foamlib_available
from ofti.foamlib_adapter import read_entry as foamlib_read_entry
from ofti.foamlib_adapter import write_entry as foamlib_write_entry

DEV_FLAG = "OFTI_MCP_DEV"
REFS_ROOT = Path("refs").resolve()

mcp = FastMCP("ofti-foamlib-dev")


def _is_case_dir(path: Path) -> bool:
    return (path / "system" / "controlDict").is_file()


def _resolve_refs_path(path: str) -> Path:
    candidate = (REFS_ROOT / path).resolve()
    if not str(candidate).startswith(str(REFS_ROOT)):
        raise ValueError("Path must stay under refs/")  # noqa: TRY003
    return candidate


@mcp.tool
def list_cases(root: str = "examples") -> list[str]:
    base = Path(root).expanduser()
    if not base.is_dir():
        return []
    cases: list[str] = []
    for entry in base.iterdir():
        if entry.is_dir() and _is_case_dir(entry):
            cases.append(str(entry))
    return sorted(cases)


@mcp.tool
def read_entry(path: str, key: str) -> str:
    file_path = Path(path).expanduser()
    if not foamlib_available():
        raise RuntimeError("foamlib not available")  # noqa: TRY003
    return foamlib_read_entry(file_path, key)


@mcp.tool
def write_entry(path: str, key: str, value: str) -> bool:
    file_path = Path(path).expanduser()
    if not foamlib_available():
        raise RuntimeError("foamlib not available")  # noqa: TRY003
    if foamlib_write_entry(file_path, key, str(value)):
        return True
    return openfoam.write_entry(file_path, key, str(value))


@mcp.tool
def boundary_matrix(case: str) -> dict[str, Any]:
    case_path = Path(case).expanduser()
    matrix = build_boundary_matrix(case_path)
    return {
        "fields": matrix.fields,
        "patches": matrix.patches,
        "patch_types": matrix.patch_types,
        "data": {
            patch: {
                field: {
                    "status": cell.status,
                    "type": cell.bc_type,
                    "value": cell.value,
                }
                for field, cell in row.items()
            }
            for patch, row in matrix.data.items()
        },
    }


@mcp.tool
def refs_list_files(path: str = "") -> list[str]:
    root = _resolve_refs_path(path)
    if root.is_file():
        return [str(root.relative_to(REFS_ROOT))]
    if not root.exists():
        return []
    return sorted(str(p.relative_to(REFS_ROOT)) for p in root.rglob("*") if p.is_file())


@mcp.tool
def refs_read_file(path: str, max_bytes: int = 20000) -> str:
    target = _resolve_refs_path(path)
    if not target.is_file():
        raise FileNotFoundError(str(target))
    data = target.read_bytes()
    if len(data) > max_bytes:
        data = data[:max_bytes]
    return data.decode(errors="ignore")


@mcp.tool
def refs_grep(pattern: str, path: str = "") -> list[str]:
    root = _resolve_refs_path(path)
    if not root.exists():
        return []
    matches: list[str] = []
    files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    for file_path in files:
        try:
            for line_no, line in enumerate(
                file_path.read_text(errors="ignore").splitlines(),
                start=1,
            ):
                if pattern in line:
                    rel = file_path.relative_to(REFS_ROOT)
                    matches.append(f"{rel}:{line_no}:{line.strip()}")
        except OSError:
            continue
    return matches


@mcp.tool
def refs_summarize_repo(
    repo: str,
    max_files: int = 200,
    max_readme_lines: int = 200,
) -> dict[str, Any]:
    root = _resolve_refs_path(repo)
    if not root.exists():
        raise FileNotFoundError(str(root))
    if root.is_file():
        root = root.parent

    py_files = sorted(p for p in root.rglob("*.py") if p.is_file())
    if len(py_files) > max_files:
        py_files = py_files[:max_files]

    public_symbols: dict[str, list[str]] = {}
    for file_path in py_files:
        try:
            tree = ast.parse(file_path.read_text(errors="ignore"))
        except (OSError, SyntaxError):
            continue
        exports: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
                exports.append(node.name)
        if exports:
            rel = str(file_path.relative_to(root))
            public_symbols[rel] = exports[:50]

    readme_hits: list[str] = []
    for candidate in ("README.md", "readme.md", "README.rst", "readme.rst"):
        readme_path = root / candidate
        if readme_path.is_file():
            lines = readme_path.read_text(errors="ignore").splitlines()
            for line in lines:
                lower = line.strip().lower()
                if lower.startswith("#") and any(
                    token in lower for token in ("feature", "usage", "overview", "install")
                ):
                    readme_hits.append(line.strip())
                if len(readme_hits) >= max_readme_lines:
                    break
        if readme_hits:
            break

    return {
        "repo": str(root.relative_to(REFS_ROOT)),
        "python_files_scanned": len(py_files),
        "public_symbols": public_symbols,
        "readme_headings": readme_hits,
    }


@mcp.tool
def foamlib_version() -> str:
    try:
        import foamlib  # local import for optional dependency
    except Exception as exc:  # pragma: no cover - dev only
        raise RuntimeError(f"foamlib import failed: {exc}")  # noqa: TRY003
    return getattr(foamlib, "__version__", "unknown")


@mcp.tool
def foamlib_api_overview() -> dict[str, Any]:
    import foamlib  # local import for optional dependency

    def _public(obj: Any) -> list[str]:
        return sorted(name for name in dir(obj) if not name.startswith("_"))

    overview: dict[str, Any] = {"module": _public(foamlib)}
    for name in ("FoamCase", "FoamFile", "FoamFieldFile"):
        cls = getattr(foamlib, name, None)
        if cls is None:
            continue
        overview[name] = _public(cls)
    return overview


@mcp.tool
def foamlib_symbol(name: str) -> dict[str, Any]:
    import foamlib  # local import for optional dependency

    target = None
    if "." in name:
        root_name, attr = name.split(".", 1)
        root = getattr(foamlib, root_name, None)
        if root is not None:
            target = getattr(root, attr, None)
    else:
        target = getattr(foamlib, name, None)
    if target is None:
        raise ValueError(f"Unknown foamlib symbol: {name}")  # noqa: TRY003
    doc = inspect.getdoc(target) or ""
    try:
        sig = str(inspect.signature(target))
    except Exception:
        sig = ""
    return {"name": name, "signature": sig, "doc": doc}


def main() -> int:
    if os.environ.get(DEV_FLAG) != "1":
        sys.stderr.write(
            "ofti-foamlib-mcp is development-only. "
            f"Set {DEV_FLAG}=1 to run.\n",
        )
        return 2
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
