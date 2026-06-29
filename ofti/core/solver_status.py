from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import log10
from pathlib import Path
from typing import Any

from ofti.core.checkmesh import extract_last_courant
from ofti.foamlib.logs import parse_residuals


@dataclass(frozen=True)
class SolverJobSummary:
    name: str
    status: str
    returncode: int | None
    started_at: float | None


def latest_solver_job(case_path: Path, solver: str) -> SolverJobSummary | None:
    from ofti.tools.job_registry import refresh_jobs

    jobs = refresh_jobs(case_path)
    solver_jobs = [job for job in jobs if job.get("name") == solver]
    if not solver_jobs:
        return None
    last = max(solver_jobs, key=lambda job: job.get("started_at") or 0)
    return SolverJobSummary(
        name=solver,
        status=_str_value(last.get("status"), default="unknown"),
        returncode=_int_or_none(last.get("returncode")),
        started_at=_float_or_none(last.get("started_at")),
    )


def _str_value(value: Any, *, default: str) -> str:
    return value if isinstance(value, str) else default


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _float_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def solver_status_text(summary: SolverJobSummary) -> str:
    if summary.status == "running":
        return f"{summary.name} running"
    if summary.status == "finished":
        rc = summary.returncode
        if rc is None:
            return f"{summary.name} finished"
        if rc == 0:
            return f"{summary.name} last exit 0"
        return f"{summary.name} failed (exit {rc})"
    return f"{summary.name} {summary.status}"


def last_solver_time(lines: Iterable[str]) -> str | None:
    for line in reversed(list(lines)):
        if "Time =" in line:
            parts = line.split("Time =", 1)
            if len(parts) == 2:
                return parts[1].strip().split()[0]
    return None


def fatal_log_line(lines: Iterable[str]) -> str | None:
    markers = [
        "FOAM FATAL ERROR",
        "FATAL ERROR",
        "Cannot open file",
        "cannot open file",
        "cannot find file",
        "No such file",
        "file: ",
    ]
    for line in reversed(list(lines)):
        for marker in markers:
            if marker in line:
                return line.strip()
    return None


def residual_spark_lines(lines: Iterable[str], width: int) -> list[str]:
    text = "\n".join(lines)
    residuals = parse_residuals(text)
    if not residuals:
        return []
    plot_width = max(10, min(30, width - 28))
    preferred = ["p", "U", "Ux", "Uy", "Uz", "k", "omega", "epsilon"]
    ordered = [field for field in preferred if field in residuals]
    ordered += sorted(field for field in residuals if field not in ordered)
    lines_out: list[str] = []
    for field in ordered[:2]:
        values = residuals.get(field, [])
        if not values:
            continue
        plot = _sparkline(values, plot_width)
        last = values[-1]
        lines_out.append(f"Res {field:>6} {plot} last={last:.2g}")
    return lines_out


def last_courant_value(lines: Iterable[str]) -> float | None:
    return extract_last_courant(list(lines))


def _sparkline(values: list[float], width: int) -> str:
    if not values or width <= 0:
        return ""
    sample = _sparkline_sample(values, width)
    safe = [val if val > 0 else 1e-16 for val in sample]
    scaled, vmin, vmax = _sparkline_scale(safe)

    levels = " .:-=+*#%@"
    span = vmax - vmin
    if span <= 0:
        return levels[-1] * len(sample)
    chars = []
    for val in scaled:
        norm = (val - vmin) / span
        idx = round(norm * (len(levels) - 1))
        idx = max(0, min(len(levels) - 1, idx))
        chars.append(levels[idx])
    return "".join(chars)


def _sparkline_sample(values: list[float], width: int) -> list[float]:
    if len(values) <= width:
        return values
    step = len(values) / width
    return [values[int(i * step)] for i in range(width)]


def _sparkline_scale(values: list[float]) -> tuple[list[float], float, float]:
    vmin = min(values)
    vmax = max(*values, 1e-16)
    ratio = vmax / vmin if vmin > 0 else vmax
    if ratio <= 1e3:
        return values, vmin, vmax
    scaled = [log10(val) for val in values]
    return scaled, min(scaled), max(scaled)
