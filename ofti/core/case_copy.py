from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

_RUNTIME_DIR_NAMES = {"postProcessing", ".ofti", "__pycache__"}


def copy_case_directory(
    source_case: Path,
    destination: Path,
    *,
    include_runtime_artifacts: bool = False,
    drop_mesh: bool = False,
    keep_zero_directory: bool = True,
) -> Path:
    source_path = source_case.expanduser().resolve()
    if not source_path.is_dir():
        raise ValueError(f"source case directory not found: {source_path}")
    if not (source_path / "system" / "controlDict").is_file():
        raise ValueError(f"source case is missing system/controlDict: {source_path}")

    dest_path = destination.expanduser()
    if not dest_path.is_absolute():
        dest_path = source_path.parent / dest_path
    dest_path = dest_path.resolve()
    if dest_path.exists():
        raise ValueError(f"destination already exists: {dest_path}")
    try:
        dest_path.relative_to(source_path)
    except ValueError:
        pass
    else:
        raise ValueError(f"destination must be outside source case: {dest_path}")

    ignore = _build_copy_ignore(
        source_path,
        include_runtime_artifacts=include_runtime_artifacts,
        drop_mesh=drop_mesh,
        keep_zero_directory=keep_zero_directory,
    )
    shutil.copytree(source_path, dest_path, symlinks=True, ignore=ignore)
    return dest_path


def _build_copy_ignore(
    source_case: Path,
    *,
    include_runtime_artifacts: bool,
    drop_mesh: bool,
    keep_zero_directory: bool,
) -> Callable[[str, list[str]], set[str]]:
    source_root = source_case.resolve()

    def _ignore(current: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        current_path = Path(current).resolve()
        try:
            relative = current_path.relative_to(source_root)
        except ValueError:
            return ignored
        if relative == Path() and not include_runtime_artifacts:
            ignored |= {
                name
                for name in names
                if _is_runtime_artifact_name(name, keep_zero_directory=keep_zero_directory)
            }
        if relative == Path("constant") and drop_mesh and "polyMesh" in names:
            ignored.add("polyMesh")
        return ignored

    return _ignore


def _is_runtime_artifact_name(name: str, *, keep_zero_directory: bool) -> bool:
    if name in _RUNTIME_DIR_NAMES:
        return True
    if name.startswith("processor"):
        return True
    if name.startswith("log."):
        return True
    if name.endswith(".foam"):
        return True
    if _is_time_dir_name(name):
        return not (keep_zero_directory and name == "0")
    return False


def _is_time_dir_name(name: str) -> bool:
    try:
        value = float(name)
    except ValueError:
        return False
    return value >= 0
