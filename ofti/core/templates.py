from __future__ import annotations

from pathlib import Path


def _examples_root() -> Path | None:
    # Prefer repo-local examples when running from source.
    candidates = [
        Path(__file__).resolve().parents[2] / "examples",
        Path.cwd() / "examples",
    ]
    for root in candidates:
        if root.is_dir():
            return root
    return None


def iter_example_cases() -> list[Path]:
    root = _examples_root()
    if root is None:
        return []
    return sorted([p for p in root.iterdir() if p.is_dir()])


def load_example_template(rel_path: Path) -> str | None:
    """
    Return the content of an example file matching rel_path (relative to case root),
    or None if no example file exists.
    """
    for case_dir in iter_example_cases():
        candidate = case_dir / rel_path
        if candidate.is_file():
            try:
                return candidate.read_text(errors="ignore")
            except OSError:
                return None
    return None


def write_example_template(dest: Path, rel_path: Path) -> bool:
    """
    Write example content to dest if available. Returns True on success.
    """
    content = load_example_template(rel_path)
    if content is None:
        return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    except OSError:
        return False
    return True


def find_example_file(rel_path: Path) -> Path | None:
    for case_dir in iter_example_cases():
        candidate = case_dir / rel_path
        if candidate.is_file():
            return candidate
    return None
