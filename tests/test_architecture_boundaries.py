from __future__ import annotations

import ast
from pathlib import Path

UI_PREFIXES = ("ofti.app", "ofti.ui", "ofti.ui_curses")
UPSTREAM_FOAMLIB = "foamlib"

# Legacy TUI-screen modules still live under ofti/tools. This list makes the
# debt explicit and prevents it from spreading while the lib/adapter split is
# completed.
KNOWN_UI_IN_TOOLS: set[Path] = set()
KNOWN_DIRECT_FOAMLIB: set[Path] = set()


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _py_files(root: str) -> list[Path]:
    return sorted(Path(root).rglob("*.py"))


def test_new_library_modules_do_not_import_ui_adapters() -> None:
    offenders: dict[Path, list[str]] = {}
    for path in _py_files("ofti/core") + _py_files("ofti/foam") + _py_files("ofti/tools"):
        imports = _imports(path)
        bad = [name for name in imports if name.startswith(UI_PREFIXES)]
        if bad and path not in KNOWN_UI_IN_TOOLS:
            offenders[path] = bad
    assert offenders == {}


def test_known_ui_debt_list_matches_current_tree() -> None:
    current = set()
    for path in _py_files("ofti/tools"):
        imports = _imports(path)
        if any(name.startswith(UI_PREFIXES) for name in imports):
            current.add(path)
    assert current == KNOWN_UI_IN_TOOLS


def test_upstream_foamlib_imports_are_confined_or_declared() -> None:
    offenders: dict[Path, list[str]] = {}
    roots = _py_files("ofti/core") + _py_files("ofti/foam") + _py_files("ofti/tools")
    for path in roots:
        imports = _imports(path)
        bad = [
            name
            for name in imports
            if name == UPSTREAM_FOAMLIB or name.startswith(f"{UPSTREAM_FOAMLIB}.")
        ]
        if bad and path not in KNOWN_DIRECT_FOAMLIB:
            offenders[path] = bad
    assert offenders == {}
