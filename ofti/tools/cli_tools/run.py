from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TypedDict

from ofti.core.solver_checks import resolve_solver_name, validate_initial_fields
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
from ofti.tools import runner_service
from ofti.tools.helpers import with_bashrc
from ofti.tools.job_registry import register_job
from ofti.tools.tool_catalog import tool_catalog

from .common import require_case_dir

RunResult = runner_service.RunResult


class ToolCatalogPayload(TypedDict):
    case: str
    tools: list[str]


def tool_catalog_names(case_dir: Path) -> list[str]:
    payload = tool_catalog_payload(case_dir)
    return list(payload["tools"])


def tool_catalog_payload(case_dir: Path) -> ToolCatalogPayload:
    case_path = require_case_dir(case_dir)
    names = [name for name, _ in tool_catalog(case_path)]
    return {"case": str(case_path.resolve()), "tools": names}


def write_tool_catalog_json(case_dir: Path, output_path: Path | None = None) -> Path:
    case_path = require_case_dir(case_dir)
    payload = tool_catalog_payload(case_path)
    destination = output_path if output_path is not None else Path(".ofti/tool_catalog.json")
    if not destination.is_absolute():
        destination = case_path / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return destination.resolve()


def resolve_tool(case_dir: Path, name: str) -> tuple[str, list[str]] | None:
    case_path = require_case_dir(case_dir)
    catalog = tool_catalog(case_path)
    normalized = _normalize_name(name)
    for display, cmd in catalog:
        if display == name or _normalize_name(display) == normalized:
            return display, list(cmd)
    return None


def solver_command(
    case_dir: Path,
    *,
    solver: str | None = None,
    parallel: int = 0,
    mpi: str | None = None,
) -> tuple[str, list[str]]:
    case_path = require_case_dir(case_dir)
    chosen_solver = solver
    if not chosen_solver:
        chosen_solver, error = resolve_solver_name(case_path)
        if error:
            raise ValueError(f"Cannot resolve solver: {error}")
    if not chosen_solver:
        raise ValueError("Cannot resolve solver from case.")

    errors = validate_initial_fields(case_path)
    if errors:
        raise ValueError("\n".join(errors))

    cmd = [chosen_solver]
    if parallel > 1:
        launcher = mpi or detect_mpi_launcher()
        if not launcher:
            raise ValueError("MPI launcher not found (tried mpirun, mpiexec).")
        cmd = [launcher, "-np", str(parallel), chosen_solver, "-parallel"]
    display = f"{chosen_solver}-parallel" if parallel > 1 else chosen_solver
    return display, cmd


def execute_case_command(
    case_dir: Path,
    name: str,
    cmd: list[str],
    *,
    background: bool,
    detached: bool = True,
    log_path: Path | None = None,
    pid_path: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> RunResult:
    case_path = require_case_dir(case_dir)
    return runner_service.execute_case_command(
        case_path,
        name,
        cmd,
        background=background,
        detached=detached,
        log_path=log_path,
        pid_path=pid_path,
        extra_env=extra_env,
        with_bashrc_fn=with_bashrc,
        run_trusted_fn=run_trusted,
        popen_fn=subprocess.Popen,
        register_job_fn=register_job,
    )


def dry_run_command(cmd: list[str]) -> str:
    return runner_service.dry_run_command(cmd, with_bashrc_fn=with_bashrc)


def detect_mpi_launcher() -> str | None:
    for candidate in ("mpirun", "mpiexec"):
        try:
            return resolve_executable(candidate)
        except FileNotFoundError:
            continue
    return None


def _normalize_name(value: str) -> str:
    lowered = value.strip().lower()
    return "".join(ch for ch in lowered if ch.isalnum() or ch in {"-", "_", ".", ":"})
