from __future__ import annotations

from pathlib import Path

from ofti.foam import openfoam


def list_keywords(file_path: Path) -> list[str]:
    return openfoam.list_keywords(file_path)


def list_subkeys(file_path: Path, entry: str) -> list[str]:
    return openfoam.list_subkeys(file_path, entry)


def read_entry(file_path: Path, key: str) -> str:
    return openfoam.read_entry(file_path, key)


def write_entry(file_path: Path, key: str, value: str) -> bool:
    return openfoam.write_entry(file_path, key, value)
