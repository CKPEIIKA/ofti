from __future__ import annotations

import ast
import re
from pathlib import Path

UI_PREFIXES = ("ofti.app", "ofti.ui", "ofti.ui_curses")
CLI_ADAPTER_PREFIX = "ofti.app.cli_adapters"
UPSTREAM_FOAMLIB = "foamlib"

# Legacy TUI-screen modules still live under ofti/tools. This list makes the
# debt explicit and prevents it from spreading while the lib/adapter split is
# completed.
KNOWN_UI_IN_TOOLS: set[Path] = set()
KNOWN_DIRECT_FOAMLIB: set[Path] = set()
KNOWN_DOMAIN_TERMS: set[Path] = set()
DOMAIN_FORBIDDEN_RE = re.compile(
    r"hy2Foam|air5|air11|N2\+|O2\+|NO\+|\be-\b|\belectron\b|\bion(?:ized|s)?\b",
)


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


def test_library_modules_do_not_import_cli_adapters() -> None:
    offenders: dict[Path, list[str]] = {}
    for path in _py_files("ofti/core") + _py_files("ofti/foam") + _py_files("ofti/tools"):
        imports = _imports(path)
        bad = [name for name in imports if name.startswith(CLI_ADAPTER_PREFIX)]
        if bad:
            offenders[path] = bad
    assert offenders == {}


_RAW_SUBPROCESS_RE = re.compile(r"\bsubprocess\b|\bPopen\b|\bos\.(system|exec|spawn)")


def test_core_does_not_use_raw_subprocess() -> None:
    # ofti/core stays pure: OpenFOAM tool execution must go through the foam
    # trusted-subprocess boundary (ofti.foam.subprocess_utils.run_trusted), never
    # raw subprocess/Popen/os.system.
    offenders: dict[Path, list[str]] = {}
    for path in _py_files("ofti/core"):
        matches = sorted(set(_RAW_SUBPROCESS_RE.findall(path.read_text(encoding="utf-8"))))
        if matches:
            offenders[path] = matches
    assert offenders == {}


def test_core_subprocess_access_is_only_via_foam_boundary() -> None:
    # The only sanctioned subprocess gateway for core is the foam boundary.
    for path in _py_files("ofti/core"):
        for name in _imports(path):
            if "subprocess" in name:
                assert name == "ofti.foam.subprocess_utils", f"{path} imports {name}"


def test_core_and_tools_do_not_spread_hy2foam_domain_terms() -> None:
    offenders: dict[Path, list[str]] = {}
    for path in _py_files("ofti/core") + _py_files("ofti/tools"):
        if path in KNOWN_DOMAIN_TERMS:
            continue
        matches = sorted(set(DOMAIN_FORBIDDEN_RE.findall(path.read_text(encoding="utf-8"))))
        if matches:
            offenders[path] = matches
    assert offenders == {}
