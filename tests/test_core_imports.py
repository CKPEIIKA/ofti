from __future__ import annotations

import ast
from pathlib import Path


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_core_modules_do_not_import_ui_or_curses() -> None:
    core_dir = Path("ofti") / "core"
    py_files = sorted(core_dir.glob("*.py"))
    assert py_files, "Expected core modules to exist"

    for path in py_files:
        tree = ast.parse(path.read_text())
        imports = _imported_modules(tree)
        for module in imports:
            assert not module.startswith("curses"), f"{path} imports curses"
            assert not module.startswith("ofti.ui_curses"), f"{path} imports UI code"
