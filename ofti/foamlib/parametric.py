from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from pathlib import Path

from ofti.foam import openfoam
from ofti.foamlib.adapter import write_entry

try:  # pragma: no cover - optional preprocessing extras
    from foamlib.preprocessing.case_modifier import CaseModifier, CaseParameter
    from foamlib.preprocessing.of_dict import FoamDictAssignment, FoamDictInstruction
    FOAMLIB_PREPROCESSING = True
except Exception:  # pragma: no cover - optional fallback
    CaseModifier = None  # type: ignore[assignment]
    CaseParameter = None  # type: ignore[assignment]
    FoamDictAssignment = None  # type: ignore[assignment]
    FoamDictInstruction = None  # type: ignore[assignment]
    FOAMLIB_PREPROCESSING = False


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
    if FOAMLIB_PREPROCESSING:
        created = _build_parametric_cases_preprocessing(
            case_path,
            dict_path,
            entry,
            values,
            output_root=output_root,
        )
        if created:
            return created

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


def _build_parametric_cases_preprocessing(
    case_path: Path,
    dict_path: Path,
    entry: str,
    values: Iterable[str],
    *,
    output_root: Path | None = None,
) -> list[Path]:
    if not FOAMLIB_PREPROCESSING:
        return []
    if (
        CaseModifier is None
        or FoamDictAssignment is None
        or FoamDictInstruction is None
        or CaseParameter is None
    ):
        return []
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
        instruction = FoamDictInstruction(
            file_name=dict_path,
            keys=[part for part in entry.split(".") if part],
        )
        assignment = FoamDictAssignment(instruction=instruction, value=value)
        case_mod = CaseModifier(
            template_case=case_path,
            output_case=dest,
            key_value_pairs=[assignment],
            case_parameters=[
                CaseParameter(category="entry", name=entry),
                CaseParameter(category="value", name=value),
            ],
        )
        case_mod.create_case()
        case_mod.modify_case()
        created.append(dest)
    return created
