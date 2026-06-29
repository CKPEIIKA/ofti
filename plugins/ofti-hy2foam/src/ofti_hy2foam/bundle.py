from __future__ import annotations

from pathlib import Path


class Hy2FoamBundleHints:
    name = "hy2foam"

    def bundle_hints(self, case_dir: Path) -> tuple[str, ...]:
        if not _looks_like_hy2foam(case_dir):
            return ()
        return (
            "plugin ofti-hy2foam: target host needs compatible "
            "OpenFOAM/hyStrath/hy2Foam runtime libraries",
            "plugin ofti-hy2foam: verify thermo, chemistry, transport, "
            "and species order files on target host",
        )


def _looks_like_hy2foam(case_dir: Path) -> bool:
    markers = ("hy2Foam", "hyStrath", "Tt", "Tv", "speciesOrder")
    for rel in (Path("system") / "controlDict", Path("constant")):
        path = case_dir / rel
        text = _read_tree(path) if path.is_dir() else _read_file(path)
        if any(marker in text for marker in markers):
            return True
    return any((case_dir / "0" / field).is_file() for field in ("Tt", "Tv", "Tov"))


def _read_tree(path: Path) -> str:
    chunks: list[str] = []
    for item in sorted(path.rglob("*")):
        if item.is_file():
            chunks.append(_read_file(item))
    return "\n".join(chunks)


def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
