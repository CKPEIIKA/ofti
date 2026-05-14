from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core import run_manifest as manifest_ops
from ofti.core.case import detect_solver
from ofti.foam import run_provenance
from ofti.foam.openfoam_env import detect_openfoam_version, resolve_openfoam_bashrc


def build_run_manifest(case_path: Path, **kwargs: Any) -> dict[str, Any]:
    bashrc = resolve_openfoam_bashrc()
    solver_name = kwargs.get("solver_name") or detect_solver(case_path)
    provenance = run_provenance.build_provenance(str(solver_name), bashrc=bashrc)
    return manifest_ops.build_run_manifest(
        case_path,
        **kwargs,
        openfoam_bashrc=bashrc,
        openfoam_version=detect_openfoam_version(),
        build_provenance=provenance,
        source_info=run_provenance.git_info(case_path),
    )


def write_case_run_manifest(case_path: Path, **kwargs: Any) -> Path:
    bashrc = resolve_openfoam_bashrc()
    solver_name = kwargs.get("solver_name") or detect_solver(case_path)
    provenance = run_provenance.build_provenance(str(solver_name), bashrc=bashrc)
    return manifest_ops.write_case_run_manifest(
        case_path,
        **kwargs,
        openfoam_bashrc=bashrc,
        openfoam_version=detect_openfoam_version(),
        build_provenance=provenance,
        source_info=run_provenance.git_info(case_path),
    )


def verify_run_manifest(manifest_path: Path, *, case_path: Path | None = None) -> dict[str, Any]:
    manifest = manifest_ops.load_run_manifest(manifest_path)
    return manifest_ops.verify_run_manifest(
        manifest_path,
        case_path=case_path,
        openfoam_version=detect_openfoam_version(),
        build_provenance_check=run_provenance.verify_build_provenance(manifest),
    )


restore_run_manifest = manifest_ops.restore_run_manifest
load_run_manifest = manifest_ops.load_run_manifest
write_run_manifest = manifest_ops.write_run_manifest
resolve_manifest_output = manifest_ops.resolve_manifest_output
