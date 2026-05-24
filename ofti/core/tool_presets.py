from __future__ import annotations

import shlex
from pathlib import Path


def load_presets_from_path(cfg_path: Path) -> list[tuple[str, list[str]]]:
    presets: list[tuple[str, list[str]]] = []
    if not cfg_path.is_file():
        return presets

    try:
        lines = cfg_path.read_text().splitlines()
    except OSError:
        return presets

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        name, cmd_str = line.split(":", 1)
        name = name.strip()
        cmd_str = cmd_str.strip()
        if not name or not cmd_str:
            continue
        try:
            cmd = shlex.split(cmd_str)
        except ValueError:
            continue
        presets.append((name, cmd))
    return presets


def load_tool_presets(case_path: Path) -> list[tuple[str, list[str]]]:
    return load_presets_from_path(case_path / "ofti.tools")


def load_postprocessing_presets(case_path: Path) -> list[tuple[str, list[str]]]:
    return load_presets_from_path(case_path / "ofti.postprocessing")
