from __future__ import annotations

import os
import re
from dataclasses import dataclass

from ofti.foam.openfoam_env import detect_openfoam_version


@dataclass(frozen=True)
class OpenFOAMVersionInfo:
    version: str
    fork: str
    legacy: bool


def detect_version_info() -> OpenFOAMVersionInfo:
    version = detect_openfoam_version()
    fork = detect_openfoam_fork()
    legacy = is_legacy_version(version, fork=fork)
    return OpenFOAMVersionInfo(version=version, fork=fork, legacy=legacy)


def detect_openfoam_fork() -> str:
    project = os.environ.get("WM_PROJECT", "")
    project_dir = os.environ.get("WM_PROJECT_DIR", "")
    lowered = f"{project} {project_dir}".lower()
    if "foam-extend" in lowered or "foamextend" in lowered:
        return "foam-extend"
    if "openfoam" in lowered:
        return "openfoam"
    return "unknown"


def is_legacy_version(version: str, *, fork: str | None = None) -> bool:
    if fork and fork != "unknown":
        if fork == "foam-extend":
            return True
        if fork == "openfoam":
            return False

    value = version.strip().lower()
    if not value or value == "unknown":
        return False
    if value.startswith("v") and len(value) > 3:
        return False
    match = re.match(r"^(\d+)(?:\.(\d+))?", value)
    if match:
        major = int(match.group(1))
        return major < 3
    return False


def get_dict_path(kind: str, *, version: str | None = None, fork: str | None = None) -> str:
    key = kind.strip().lower()
    if version is None:
        info = detect_version_info()
        version = info.version
        fork = info.fork
    legacy = is_legacy_version(version, fork=fork)
    mappings = {
        "turbulence": "constant/RASProperties"
        if legacy
        else "constant/turbulenceProperties",
        "turbulenceproperties": "constant/RASProperties"
        if legacy
        else "constant/turbulenceProperties",
        "thermophysical": "constant/thermophysicalProperties",
        "thermophysicalproperties": "constant/thermophysicalProperties",
        "transport": "constant/transportProperties",
        "transportproperties": "constant/transportProperties",
        "fvsolution": "system/fvSolution",
        "fvschemes": "system/fvSchemes",
        "controldict": "system/controlDict",
        "control": "system/controlDict",
        "blockmeshdict": "system/blockMeshDict",
    }
    return mappings.get(key, key)


def solver_aliases(*, version: str | None = None, fork: str | None = None) -> dict[str, str]:
    if version is None:
        info = detect_version_info()
        version = info.version
        fork = info.fork
    legacy = is_legacy_version(version, fork=fork)

    return {
        "compressible": "rhoCentralFoam" if legacy else "rhoPimpleFoam",
        "incompressible": "simpleFoam",
        "transient_incompressible": "pimpleFoam",
    }


def resolve_solver_alias(alias: str, *, version: str | None = None, fork: str | None = None) -> str:
    key = alias.strip().lower().replace(" ", "_")
    aliases = solver_aliases(version=version, fork=fork)
    return aliases.get(key, alias)
