"""Bounded solver smoke-test payloads (extracted from cli_tools.run).

Execution helpers (solver_command, prepare_parallel_case, dry_run_command) stay
in cli_tools.run and are reached via the lazy ``_run()`` accessor so they remain
patchable and avoid an import cycle.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from ofti.core.entry_io import read_entry, write_entry
from ofti.tools import knife_service, runner_service

from .common import require_case_dir

_TIME_RE = re.compile(r"^\s*Time\s*=\s*(?P<time>[-+0-9.eE]+)\s*$", re.MULTILINE)


def _run() -> Any:
    from ofti.tools.cli_tools import run

    return run


def smoke_payload(
    case_dir: Path,
    *,
    solver: str | None = None,
    iterations: int = 20,
    timeout: float = 300.0,
    parallel: int = 0,
    mpi: str | None = None,
    output_root: Path | None = None,
    in_place: bool = False,
    delta_t: float | None = None,
    preserve_delta_t: bool = False,
    core_only: bool = False,
    prepare_parallel: bool = True,
    clean_processors: bool = False,
    run_physical: bool = False,
    physical_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Run a bounded solver smoke test on a copied case by default."""
    if iterations <= 0:
        raise ValueError("iterations must be > 0")
    if timeout <= 0:
        raise ValueError("timeout must be > 0")
    source = require_case_dir(case_dir)
    root = _smoke_output_root(source, output_root=output_root)
    smoke_case = source if in_place else root / "case"
    if not in_place:
        if smoke_case.exists():
            raise ValueError(f"smoke output case already exists: {smoke_case}")
        shutil.copytree(source, smoke_case, ignore=shutil.ignore_patterns(".ofti"))
    else:
        root.mkdir(parents=True, exist_ok=True)
    control = smoke_case / "system" / "controlDict"
    chosen_delta_t = _smoke_delta_t(control, delta_t=delta_t, preserve_delta_t=preserve_delta_t)
    normalized = _normalize_smoke_control_dict(
        control,
        iterations=iterations,
        delta_t=chosen_delta_t,
        preserve_delta_t=preserve_delta_t,
        core_only=core_only,
    )
    chosen_solver = solver or _read_control_word(control, "application")
    display, command = _run().solver_command(
        smoke_case,
        solver=chosen_solver,
        parallel=parallel,
        mpi=mpi,
    )
    parallel_setup: dict[str, Any] | None = None
    if parallel > 1 and prepare_parallel:
        parallel_setup = _run().prepare_parallel_case(
            smoke_case,
            parallel=parallel,
            clean_processors=clean_processors,
            dry_run=False,
        )
    started = time.time()
    log_path = root / f"log.{runner_service.safe_name(display)}"
    result, timed_out = _run_smoke_command(
        smoke_case,
        command,
        timeout=timeout,
        log_path=log_path,
    )
    wall_seconds = time.time() - started
    log_text = log_path.read_text(encoding="utf-8", errors="ignore") if log_path.is_file() else ""
    summary: dict[str, Any] = {
        "source_case": str(source.resolve()),
        "case": str(smoke_case.resolve()),
        "output_root": str(root.resolve()),
        "copied": not in_place,
        "solver": display,
        "command": _run().dry_run_command(command),
        "iterations_requested": int(iterations),
        "timeout_seconds": float(timeout),
        "parallel": int(parallel),
        "prepare_parallel": bool(prepare_parallel),
        "clean_processors": bool(clean_processors),
        "parallel_setup": parallel_setup,
        "normalized_control": normalized,
        "returncode": int(result.returncode),
        "timed_out": bool(timed_out),
        "wall_seconds": wall_seconds,
        "log_path": str(log_path.resolve()),
        "times_seen": _smoke_times_seen(log_text),
        "end_seen": "End" in log_text,
        "ok": int(result.returncode) == 0 and not timed_out,
    }
    if run_physical:
        summary["physical"] = knife_service.physical_payload(
            smoke_case,
            time_name="latest",
            fields=physical_fields,
            out_dir=root,
        )
    _write_smoke_reports(summary, root)
    return summary


def parse_duration_seconds(value: str | float | int) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    match = re.fullmatch(r"(?P<num>[0-9]+(?:\.[0-9]+)?)(?P<unit>ms|s|m|h)?", text)
    if match is None:
        raise ValueError(f"invalid duration: {value}")
    number = float(match.group("num"))
    unit = match.group("unit") or "s"
    factors = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return number * factors[unit]


def _smoke_output_root(source: Path, *, output_root: Path | None) -> Path:
    if output_root is not None:
        return output_root.expanduser().resolve()
    return (source / ".ofti" / "smoke" / f"smoke-{int(time.time())}").resolve()


def _smoke_delta_t(
    control: Path,
    *,
    delta_t: float | None,
    preserve_delta_t: bool,
) -> float:
    if delta_t is not None:
        return float(delta_t)
    raw = _read_control_scalar(control, "deltaT")
    if raw is not None:
        return raw
    if preserve_delta_t:
        raise ValueError("controlDict has no deltaT to preserve")
    return 1.0


def _normalize_smoke_control_dict(
    control: Path,
    *,
    iterations: int,
    delta_t: float,
    preserve_delta_t: bool,
    core_only: bool,
) -> dict[str, Any]:
    writes = {
        "startFrom": "startTime",
        "startTime": "0",
        "stopAt": "endTime",
        "endTime": f"{iterations * delta_t:g}",
        "writeControl": "timeStep",
        "writeInterval": str(iterations),
        "runTimeModifiable": "false",
    }
    if not preserve_delta_t:
        writes["deltaT"] = f"{delta_t:g}"
    if core_only:
        writes["functions"] = "{}"
    applied = {key: value for key, value in writes.items() if write_entry(control, key, value)}
    return {
        "controlDict": str(control),
        "deltaT": delta_t,
        "entries": applied,
        "core_only": bool(core_only),
    }


def _read_control_scalar(control: Path, key: str) -> float | None:
    try:
        raw = read_entry(control, key)
    except Exception:
        raw = _read_control_scalar_fallback(control, key)
    if raw is None:
        return None
    try:
        return float(str(raw).strip().rstrip(";"))
    except ValueError:
        return None


def _read_control_scalar_fallback(control: Path, key: str) -> str | None:
    try:
        text = control.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(rf"(^|\n)\s*{re.escape(key)}\s+(?P<value>[^;]+);", text)
    return match.group("value").strip() if match else None


def _read_control_word(control: Path, key: str) -> str | None:
    try:
        raw = read_entry(control, key)
    except Exception:
        raw = _read_control_scalar_fallback(control, key)
    token = str(raw or "").strip().rstrip(";").split()
    return token[0] if token else None


def _run_smoke_command(
    case_path: Path,
    command: list[str],
    *,
    timeout: float,
    log_path: Path,
) -> tuple[subprocess.CompletedProcess[str], bool]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    try:
        # Command is built by solver_command(), not shell text; timeout keeps smoke runs bounded.
        result = subprocess.run(  # noqa: S603
            command,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = _timeout_text(exc.stdout)
        stderr = _timeout_text(exc.stderr)
        result = subprocess.CompletedProcess(command, 124, stdout, stderr)
        timed_out = True
    log_path.write_text(
        f"{result.stdout or ''}{result.stderr or ''}",
        encoding="utf-8",
        errors="ignore",
    )
    return result, timed_out


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return value


def _smoke_times_seen(log_text: str) -> list[float]:
    values: list[float] = []
    for match in _TIME_RE.finditer(log_text):
        with suppress(ValueError):
            values.append(float(match.group("time")))
    return values


def _write_smoke_reports(payload: Mapping[str, Any], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        "# OFTI Smoke Run",
        "",
        f"- case: {payload.get('case')}",
        f"- solver: {payload.get('solver')}",
        f"- ok: {payload.get('ok')}",
        f"- returncode: {payload.get('returncode')}",
        f"- timed_out: {payload.get('timed_out')}",
        f"- wall_seconds: {float(payload.get('wall_seconds') or 0):.3f}",
        f"- log: {payload.get('log_path')}",
    ]
    (root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
