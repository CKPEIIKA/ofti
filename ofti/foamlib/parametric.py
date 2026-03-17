from __future__ import annotations

import itertools
import re
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ofti.core.case_copy import copy_case_directory

try:  # pragma: no cover - optional preprocessing extras
    from foamlib.preprocessing.case_modifier import CaseModifier, CaseParameter
    from foamlib.preprocessing.grid_parameter_sweep import (
        CaseParameter as GridCaseParameter,
    )
    from foamlib.preprocessing.grid_parameter_sweep import GridParameter
    from foamlib.preprocessing.of_dict import FoamDictAssignment, FoamDictInstruction
    from foamlib.preprocessing.parameter_study import csv_generator, grid_generator
    FOAMLIB_PREPROCESSING = True
except Exception:  # pragma: no cover - optional fallback
    CaseModifier = None  # type: ignore[assignment]
    CaseParameter = None  # type: ignore[assignment]
    GridCaseParameter = None  # type: ignore[assignment]
    GridParameter = None  # type: ignore[assignment]
    FoamDictAssignment = None  # type: ignore[assignment]
    FoamDictInstruction = None  # type: ignore[assignment]
    csv_generator = None  # type: ignore[assignment]
    grid_generator = None  # type: ignore[assignment]
    FOAMLIB_PREPROCESSING = False


class ParametricWriteError(RuntimeError):
    def __init__(self, entry: str, target: Path) -> None:
        super().__init__(f"Failed to set {entry} in {target}")


def preprocessing_available() -> bool:
    return bool(FOAMLIB_PREPROCESSING)


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
        if not _write_dict_entry(target_dict, entry, value):
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


def build_parametric_cases_from_csv(
    case_path: Path,
    csv_path: Path,
    *,
    output_root: Path | None = None,
) -> list[Path]:
    _require_preprocessing(
        "CSV studies require foamlib preprocessing extras. Install 'foamlib[preprocessing]'.",
    )
    assert csv_generator is not None
    output_root = output_root or case_path.parent
    csv_file = csv_path if csv_path.is_absolute() else case_path / csv_path
    if not csv_file.is_file():
        raise FileNotFoundError(csv_file)
    study = csv_generator(
        csv_file=csv_file,
        template_case=case_path,
        output_folder=output_root,
    )
    study.create_study(study_base_folder=output_root)
    return _study_cases(study)


def build_parametric_cases_from_grid(
    case_path: Path,
    axes: list[dict[str, Any]],
    *,
    output_root: Path | None = None,
) -> list[Path]:
    _require_preprocessing(
        "Grid studies require foamlib preprocessing extras. Install 'foamlib[preprocessing]'.",
    )
    if not axes:
        raise ValueError("Grid study requires at least one axis.")
    assert (
        GridParameter is not None
        and GridCaseParameter is not None
        and FoamDictInstruction is not None
        and grid_generator is not None
    )
    output_root = output_root or case_path.parent
    parameters: list[GridParameter] = []
    for axis in axes:
        dict_path = str(axis.get("dict_path") or "").strip()
        entry = str(axis.get("entry") or "").strip()
        values = [str(item).strip() for item in axis.get("values", []) if str(item).strip()]
        if not dict_path or not entry:
            raise ValueError("Each grid axis requires dictionary path and entry key.")
        if not values:
            raise ValueError(f"Grid axis '{entry}' has no values.")
        instruction = FoamDictInstruction(
            file_name=Path(dict_path),
            keys=[part for part in entry.split(".") if part],
        )
        case_parameters = [
            GridCaseParameter(name=_sanitize_value(value), values=[value])
            for value in values
        ]
        parameters.append(
            GridParameter(
                parameter_name=entry.replace(".", "_"),
                modify_dict=[instruction],
                parameters=case_parameters,
            ),
        )

    study = grid_generator(
        parameters=parameters,
        template_case=case_path,
        output_folder=output_root,
    )
    study.create_study(study_base_folder=output_root)
    return _study_cases(study)


def build_matrix_cases(
    case_path: Path,
    axes: list[dict[str, Any]],
    *,
    output_root: Path | None = None,
    case_name_fn: Callable[[list[tuple[dict[str, Any], str]]], str] | None = None,
) -> list[Path]:
    if not axes:
        return []
    output_root = output_root or case_path.parent
    combos = _matrix_combinations(axes)
    destinations: list[tuple[Path, list[tuple[dict[str, Any], str]]]] = []
    for combo in combos:
        case_name = (
            case_name_fn(combo)
            if case_name_fn is not None
            else _matrix_case_name(case_path.name, combo)
        )
        destination = output_root / case_name
        if destination.exists():
            raise FileExistsError(destination)
        destinations.append((destination, combo))

    created: list[Path] = []
    for destination, combo in destinations:
        if _build_matrix_case_preprocessing(case_path, destination, combo):
            created.append(destination)
            continue
        _build_matrix_case_fallback(case_path, destination, combo)
        created.append(destination)
    return created


def _require_preprocessing(message: str) -> None:
    if not FOAMLIB_PREPROCESSING:
        raise RuntimeError(message)


def _study_cases(study: Any) -> list[Path]:
    cases = getattr(study, "cases", [])
    result: list[Path] = []
    for case in cases:
        output_case = getattr(case, "output_case", None)
        if output_case:
            result.append(Path(output_case))
    return result


def _build_matrix_case_preprocessing(
    template_case: Path,
    destination: Path,
    combo: list[tuple[dict[str, Any], str]],
) -> bool:
    if (
        not FOAMLIB_PREPROCESSING
        or CaseModifier is None
        or FoamDictInstruction is None
        or FoamDictAssignment is None
        or CaseParameter is None
    ):
        return False
    assignments: list[Any] = []
    params: list[Any] = []
    for axis, value in combo:
        dict_path = str(axis.get("dict_path") or "").strip()
        entry = str(axis.get("entry") or "").strip()
        if not dict_path or not entry:
            return False
        instruction = FoamDictInstruction(
            file_name=Path(dict_path),
            keys=[part for part in entry.split(".") if part],
        )
        assignments.append(FoamDictAssignment(instruction=instruction, value=value))
        params.append(CaseParameter(category="entry", name=entry))
        params.append(CaseParameter(category="value", name=value))
    try:
        case_mod = CaseModifier(
            template_case=template_case,
            output_case=destination,
            key_value_pairs=assignments,
            case_parameters=params,
        )
        case_mod.create_case()
        case_mod.modify_case()
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        return False
    else:
        return True


def _build_matrix_case_fallback(
    template_case: Path,
    destination: Path,
    combo: list[tuple[dict[str, Any], str]],
) -> None:
    copy_case_directory(
        template_case,
        destination,
        include_runtime_artifacts=False,
        drop_mesh=False,
        keep_zero_directory=True,
    )
    for axis, value in combo:
        dict_path = destination / str(axis["dict_path"])
        entry = str(axis["entry"])
        if not dict_path.is_file():
            raise FileNotFoundError(dict_path)
        if not _write_dict_entry(dict_path, entry, value):
            raise ParametricWriteError(entry, dict_path)


def _matrix_combinations(axes: list[dict[str, Any]]) -> list[list[tuple[dict[str, Any], str]]]:
    value_sets = [[str(value) for value in axis.get("values", [])] for axis in axes]
    combos: list[list[tuple[dict[str, Any], str]]] = []
    for values in itertools.product(*value_sets):
        combos.append(list(zip(axes, values, strict=True)))
    return combos


def _matrix_case_name(template_name: str, combo: list[tuple[dict[str, Any], str]]) -> str:
    tokens = [template_name]
    for axis, value in combo:
        axis_label = f"{axis.get('dict_path')}:{axis.get('entry')}"
        entry_token = _sanitize_value(axis_label.replace(".", "_").replace("/", "_"))
        value_token = _sanitize_value(value)
        tokens.append(f"{entry_token}-{value_token}")
    return "__".join(tokens)


def _write_dict_entry(file_path: Path, key: str, value: str) -> bool:
    from ofti.core import entry_io

    return entry_io.write_entry(file_path, key, value)
