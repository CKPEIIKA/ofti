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


def _assert_no_ui_imports(paths: list[Path]) -> None:
    for path in paths:
        tree = ast.parse(path.read_text())
        imports = _imported_modules(tree)
        for module in imports:
            assert not module.startswith("ofti.ui_curses"), f"{path} imports ui_curses"
            assert not module.startswith("ofti.ui"), f"{path} imports ui"


def test_foam_modules_do_not_import_ui() -> None:
    foam_dir = Path("ofti") / "foam"
    py_files = sorted(foam_dir.glob("*.py"))
    assert py_files, "Expected foam modules to exist"
    _assert_no_ui_imports(py_files)


def test_ui_layer_does_not_import_ui_curses() -> None:
    ui_dir = Path("ofti") / "ui"
    py_files = sorted(ui_dir.glob("*.py"))
    assert py_files, "Expected ui modules to exist"
    for path in py_files:
        tree = ast.parse(path.read_text())
        imports = _imported_modules(tree)
        for module in imports:
            assert not module.startswith("ofti.ui_curses"), f"{path} imports ui_curses"
