from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ofti.foam import openfoam


@dataclass(frozen=True)
class DictDiff:
    rel_path: str
    missing_in_left: list[str]
    missing_in_right: list[str]
    error: str | None = None


def compare_case_dicts(left_case: Path, right_case: Path) -> list[DictDiff]:
    left_map = _case_file_map(left_case)
    right_map = _case_file_map(right_case)
    all_paths = sorted(set(left_map) | set(right_map))
    diffs: list[DictDiff] = []

    for rel_path in all_paths:
        left_path = left_map.get(rel_path)
        right_path = right_map.get(rel_path)
        if left_path is None:
            diffs.append(
                DictDiff(rel_path, missing_in_left=[rel_path], missing_in_right=[]),
            )
            continue
        if right_path is None:
            diffs.append(
                DictDiff(rel_path, missing_in_left=[], missing_in_right=[rel_path]),
            )
            continue
        try:
            left_keys = set(openfoam.list_keywords(left_path))
            right_keys = set(openfoam.list_keywords(right_path))
        except Exception as exc:
            diffs.append(
                DictDiff(rel_path, missing_in_left=[], missing_in_right=[], error=str(exc)),
            )
            continue
        missing_in_left = sorted(right_keys - left_keys)
        missing_in_right = sorted(left_keys - right_keys)
        if missing_in_left or missing_in_right:
            diffs.append(
                DictDiff(rel_path, missing_in_left, missing_in_right),
            )

    return diffs


def _case_file_map(case_path: Path) -> dict[str, Path]:
    sections = openfoam.discover_case_files(case_path)
    files: dict[str, Path] = {}
    for paths in sections.values():
        for path in paths:
            try:
                rel = path.relative_to(case_path).as_posix()
            except ValueError:
                rel = path.name
            files[rel] = path
    return files
