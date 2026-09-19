from __future__ import annotations

import argparse
from pathlib import Path

from ofti.app.cli_help import _EASY_ON_CPU_MIN_POLL_INTERVAL, _EASY_ON_CPU_TAIL_BYTES
from ofti.core import run_manifest as manifest_ops
from ofti.foam.config import get_config
from ofti.tools.cli_tools import run as run_ops


def tail_bytes_with_cpu_mode(args: argparse.Namespace) -> int | None:
    explicit = getattr(args, "tail_bytes", None)
    if explicit is not None:
        return int(explicit)
    if bool(getattr(args, "easy_on_cpu", False)):
        return _EASY_ON_CPU_TAIL_BYTES
    return None


def interval_with_cpu_mode(args: argparse.Namespace, interval: float) -> float:
    value = float(interval)
    if value <= 0:
        value = 0.25
    if bool(getattr(args, "easy_on_cpu", False)):
        value = max(value, _EASY_ON_CPU_MIN_POLL_INTERVAL)
    return value


def queue_options_from_args(
    args: argparse.Namespace,
    *,
    poll_interval: float,
    queue_root: Path | None = None,
) -> run_ops.QueueOptions:
    return run_ops.QueueOptions(
        solver=getattr(args, "solver", None),
        parallel=int(getattr(args, "parallel", 0)),
        mpi=getattr(args, "mpi", None),
        max_parallel=int(getattr(args, "max_parallel", 1)),
        poll_interval=poll_interval,
        dry_run=bool(getattr(args, "dry_run", False)),
        backend=str(getattr(args, "backend", "process")),
        prepare_parallel=bool(getattr(args, "prepare_parallel", True)),
        clean_processors=bool(getattr(args, "clean_processors", False)),
        queue_root=queue_root,
    )


def planned_manifest_path(case_dir: Path, manifest_file: object) -> Path:
    output = manifest_file if isinstance(manifest_file, Path) else _configured_manifest_root()
    return manifest_ops.resolve_manifest_output(Path(case_dir), output)


def _configured_manifest_root() -> Path | None:
    root = get_config().paths.manifest_root
    if root is None or not root.strip():
        return None
    return Path(root).expanduser()


def solver_name_for_manifest(cmd: list[str], *, parallel: int) -> str | None:
    solver = run_ops._solver_token_from_command(cmd, parallel=parallel)
    return str(solver) if solver else None


def parse_env_assignments(raw_values: object) -> dict[str, str]:
    values: list[str] = []
    if isinstance(raw_values, list):
        values = [str(item) for item in raw_values]
    payload: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"invalid --env assignment: {item}")
        key, value = item.split("=", 1)
        name = key.strip()
        if not name:
            raise ValueError(f"invalid --env assignment: {item}")
        payload[name] = value
    return payload
