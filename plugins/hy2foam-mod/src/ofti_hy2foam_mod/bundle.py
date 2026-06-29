from __future__ import annotations

from pathlib import Path


class Hy2FoamModBundleHints:
    name = "hy2foam-mod"

    def bundle_hints(self, case_dir: Path) -> tuple[str, ...]:
        if not _uses_nncompiled(case_dir):
            return ()
        return (
            "plugin hy2foam-mod: target host needs the same modified hy2Foam/NNcompiled runtime",
            "plugin hy2foam-mod: verify precompiledModel files and NN input/output "
            "order assets are present",
        )


def _uses_nncompiled(case_dir: Path) -> bool:
    markers = ("NNcompiled", "precompiledModel", "stateInputOrder", "inputOrder", "outputOrder")
    for root in (case_dir / "system", case_dir / "constant"):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and any(marker in _read(path) for marker in markers):
                return True
    return False


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")
