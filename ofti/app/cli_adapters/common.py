from __future__ import annotations

import argparse
from pathlib import Path

from ofti.app.cli_help import _EASY_ON_CPU_MIN_POLL_INTERVAL, _EASY_ON_CPU_TAIL_BYTES
from ofti.core import run_receipt as receipt_ops
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


def planned_receipt_path(case_dir: Path, receipt_file: object) -> Path:
    output = receipt_file if isinstance(receipt_file, Path) else None
    return receipt_ops.resolve_receipt_output(Path(case_dir), output)


def solver_name_for_receipt(cmd: list[str], *, parallel: int) -> str | None:
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
