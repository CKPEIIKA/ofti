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
KNOWN_OVERSIZED_MODULES: dict[Path, str] = {}
DOMAIN_FORBIDDEN_RE = re.compile(
    r"hy2Foam|air5|air11|N2\+|O2\+|NO\+|\be-\b|\belectron\b|\bion(?:ized|s)?\b",
)
MAX_PRODUCTION_MODULE_SLOC = 1000


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


def _sloc(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


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
        bad = [name for name in imports if name == UPSTREAM_FOAMLIB or name.startswith(f"{UPSTREAM_FOAMLIB}.")]
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


def test_plugin_implementations_do_not_import_cli_frameworks() -> None:
    forbidden = ("argparse", "click", "typer")
    offenders: dict[Path, list[str]] = {}
    for path in _py_files("plugins"):
        if "tests" in path.parts:
            continue
        bad = [
            name
            for name in _imports(path)
            if any(name == framework or name.startswith(f"{framework}.") for framework in forbidden)
        ]
        if bad:
            offenders[path] = bad
    assert offenders == {}


def test_cli_tools_uses_an_explicit_public_facade() -> None:
    path = Path("ofti/app/cli_tools.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden_calls = {"dir", "getattr", "globals", "locals", "setattr", "vars"}
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden_calls
    }
    private_adapter_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(CLI_ADAPTER_PREFIX)
        for alias in node.names
        if alias.name == "*" or alias.name.startswith("_")
    }

    assert calls == set()
    assert private_adapter_imports == set()
    assert set(cli_tools_public_names(tree)) == {"build_parser", "main", "ofti_version"}


def cli_tools_public_names(tree: ast.Module) -> list[str]:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        if isinstance(node.value, ast.List):
            return [
                item.value for item in node.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
    return []


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


def test_production_modules_stay_under_size_ratchet() -> None:
    roots = _py_files("ofti") + _py_files("plugins")
    oversized = {
        path: _sloc(path)
        for path in roots
        if _sloc(path) > MAX_PRODUCTION_MODULE_SLOC
        and path not in KNOWN_OVERSIZED_MODULES
        and "tests" not in path.parts
    }
    assert oversized == {}


def test_oversized_module_allowlist_matches_current_tree() -> None:
    current = {
        path
        for path in _py_files("ofti") + _py_files("plugins")
        if _sloc(path) > MAX_PRODUCTION_MODULE_SLOC and "tests" not in path.parts
    }
    assert current == set(KNOWN_OVERSIZED_MODULES)
