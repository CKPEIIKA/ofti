from __future__ import annotations

import re
from pathlib import Path


def detect_case_header_version(case_path: Path) -> str:
    control_dict = case_path / "system" / "controlDict"
    control_version = extract_header_version(control_dict)
    versions = _detected_versions(case_path, control_dict, control_version)

    if not versions:
        return "unknown"

    best_versions = _most_common_versions(versions)
    if control_version and control_version in best_versions:
        return control_version
    return sorted(best_versions)[0]


def _detected_versions(
    case_path: Path,
    control_dict: Path,
    control_version: str | None,
) -> list[str]:
    versions = [control_version] if control_version else []
    versions.extend(
        version
        for path in case_header_candidates(case_path, max_files=20)
        if path != control_dict and (version := extract_header_version(path))
    )
    return versions


def _most_common_versions(versions: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for version in versions:
        counts[version] = counts.get(version, 0) + 1
    best_count = max(counts.values())
    return [version for version, count in counts.items() if count == best_count]


def parse_header_comment_version(text: str) -> str | None:
    """Extract the version string from the ASCII banner that precedes FoamFile.
    """
    version_pattern = re.compile(r"Version:\s*([^\s|]+)", re.IGNORECASE)
    for line in text.splitlines():
        lower = line.lower()
        if "foamfile" in lower:
            break
        match = version_pattern.search(line)
        if match:
            value = match.group(1).strip().strip("|")
            if value:
                return value
    return None


def parse_foamfile_block_version(text: str) -> str | None:
    """Fallback: read the 'version' entry inside the FoamFile dictionary block.
    """
    inside_block = False
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("foamfile"):
            inside_block = True
            continue
        if inside_block and stripped.startswith("}"):
            break
        if inside_block and lower.startswith("version"):
            parts = stripped.split()
            if len(parts) >= 2:
                value = parts[1].rstrip(";")
                if value:
                    return value
    return None


def extract_header_version(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    header_version = parse_header_comment_version(text)
    if header_version:
        return header_version
    return parse_foamfile_block_version(text)


def case_header_candidates(case_path: Path, max_files: int = 20) -> list[Path]:
    candidates: list[Path] = []
    for rel in ("system", "constant", "0", "0.orig"):
        folder = case_path / rel
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if entry.is_file():
                candidates.append(entry)
            if len(candidates) >= max_files:
                return candidates
    return candidates
