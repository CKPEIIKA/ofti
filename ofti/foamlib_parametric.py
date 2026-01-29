from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from pathlib import Path

from ofti.foam import openfoam
from ofti.foamlib_adapter import write_entry


class ParametricWriteError(RuntimeError):
    def __init__(self, entry: str, target: Path) -> None:
        super().__init__(f"Failed to set {entry} in {target}")


def _sanitize_value(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe or "value"


def _default_ignore(_: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name.startswith("processor")}
    ignored |= {name for name in names if name.startswith("log.")}
    ignored |= {"postProcessing", "case.foam"}
    return ignored


def build_parametric_cases(
    case_path: Path,
    dict_path: Path,
    entry: str,
    values: Iterable[str],
    *,
    output_root: Path | None = None,
) -> list[Path]:
    output_root = output_root or case_path.parent
    created: list[Path] = []

    for raw_value in values:
        value = raw_value.strip()
        if not value:
            continue
        suffix = _sanitize_value(value)
        dest = output_root / f"{case_path.name}_{entry.replace('.', '_')}_{suffix}"
        if dest.exists():
            raise FileExistsError(dest)
        shutil.copytree(case_path, dest, ignore=_default_ignore)
        target_dict = dest / dict_path
        if not target_dict.is_file():
            raise FileNotFoundError(target_dict)
        if not write_entry(target_dict, entry, value) and not openfoam.write_entry(
            target_dict, entry, value,
        ):
            raise ParametricWriteError(entry, target_dict)
        created.append(dest)

    return created
