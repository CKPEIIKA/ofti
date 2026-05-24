from __future__ import annotations

import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ofti.core.case import read_number_of_subdomains, set_start_from_latest
from ofti.core.case_snapshot import write_case_snapshot
from ofti.core.times import latest_time
from ofti.core.tool_dicts_service import apply_assignment_or_write
from ofti.tools import case_source_service, knife_service, watch_service
from ofti.tools.cli_tools import run as run_ops

_DEFAULT_STOP_TIMEOUT = 45.0
_INPUT_ROOTS = ("system", "constant", "0")
_SUBDOMAINS_RE = re.compile(
    r"(^|\n)(?P<prefix>\s*numberOfSubdomains\s+)(?P<value>[0-9]+(?:\.0+)?)(?P<suffix>\s*;)",
    re.MULTILINE,
)


def parallel_resize_payload(
    case_dir: Path,
    *,
    to_ranks: int,
    from_ranks: int | None = None,
    dry_run: bool = False,
    start: bool = True,
    write_now: bool = True,
    force_stop: bool = False,
    clean_processors: bool = True,
    stop_timeout: float = _DEFAULT_STOP_TIMEOUT,
) -> dict[str, Any]:
    """Safely move a decomposed case to a new MPI rank count."""
    case_path = case_source_service.require_case_dir(case_dir)
    if to_ranks <= 1:
        raise ValueError("--to must be greater than 1 for a parallel resize")
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        raise ValueError("system/decomposeParDict is required for parallel resize")
    current_ranks = read_number_of_subdomains(decompose_dict)
    if from_ranks is not None and current_ranks not in {None, from_ranks}:
        raise ValueError(
            f"--from={from_ranks} does not match decomposeParDict={current_ranks}",
        )

    steps: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "case": str(case_path),
        "from": current_ranks,
        "to": int(to_ranks),
        "dry_run": bool(dry_run),
        "start": bool(start),
        "ok": True,
        "pid": None,
        "log_path": None,
        "snapshot_path": None,
        "input_snapshot_path": None,
        "rollback": None,
        "steps": steps,
    }
    processor_dirs = _processor_dirs(case_path)
    payload["decomposed"] = bool(processor_dirs)
    payload["processor_dirs"] = [path.name for path in processor_dirs]
    _add_plan_steps(steps, to_ranks=to_ranks, start=start, write_now=write_now)
    if dry_run:
        payload["rollback"] = _rollback_guidance(case_path, None)
        return payload

    try:
        _require_decomposed_case(processor_dirs)
        snapshot_dir = _write_full_input_snapshot(case_path)
        case_snapshot = write_case_snapshot(case_path, snapshot_dir / "case_snapshot.json")
        payload["input_snapshot_path"] = str(snapshot_dir)
        payload["snapshot_path"] = str(case_snapshot)
        payload["rollback"] = _rollback_guidance(case_path, snapshot_dir)
        _mark_step(steps, "snapshot", "done", output=str(snapshot_dir))
        if write_now:
            evidence = _request_write_now_and_wait(
                case_path,
                timeout=stop_timeout,
                force_stop=force_stop,
            )
            _mark_step(steps, "write-now", "done", **evidence)
        _run_tool_step(case_path, steps, "reconstruct", ["reconstructPar", "-latestTime"])
        _clean_processor_dirs(case_path, steps, enabled=clean_processors)
        _set_subdomains(decompose_dict, to_ranks)
        _mark_step(steps, "set-subdomains", "done")
        _resume_from_latest(case_path)
        _mark_step(steps, "resume-from-latest", "done", latest=latest_time(case_path))
        _run_tool_step(case_path, steps, "decompose", ["decomposePar", "-force", "-latestTime"])
        if start:
            display, command = run_ops.solver_command(
                case_path,
                parallel=to_ranks,
                sync_subdomains=False,
            )
            result = run_ops.execute_solver_case_command(
                case_path,
                display,
                command,
                parallel=to_ranks,
                background=True,
            )
            payload["pid"] = result.pid
            payload["log_path"] = str(result.log_path) if result.log_path else None
            _mark_step(steps, "start", "done", pid=result.pid, log_path=payload["log_path"])
    except (OSError, RuntimeError, ValueError) as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        _mark_first_pending_failed(steps, str(exc))
    return payload


def _add_plan_steps(
    steps: list[dict[str, Any]],
    *,
    to_ranks: int,
    start: bool,
    write_now: bool,
) -> None:
    planned = [
        ("snapshot", "copy system/, constant/, 0/ and write case snapshot", None),
        ("write-now", "set controlDict stopAt=writeNow and wait for live stop", None),
        ("reconstruct", "reconstruct latest decomposed time", "reconstructPar -latestTime"),
        ("clean-processors", "remove old processor* directories", None),
        ("set-subdomains", f"set numberOfSubdomains={to_ranks}", None),
        ("resume-from-latest", "set startFrom=latestTime and stopAt=endTime", None),
        ("decompose", "decompose reconstructed latest time", "decomposePar -force -latestTime"),
        ("start", f"start solver with np={to_ranks}", None),
    ]
    for step, label, command in planned:
        status = "pending"
        if (step == "write-now" and not write_now) or (step == "start" and not start):
            status = "skipped"
        steps.append({"step": step, "status": status, "label": label, "command": command})


def _write_full_input_snapshot(case_path: Path) -> Path:
    root = case_path / ".ofti" / "parallel-resize" / _timestamp()
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    for name in _INPUT_ROOTS:
        source = case_path / name
        destination = inputs / name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        elif source.exists():
            shutil.copy2(source, destination)
    return root


def _rollback_guidance(case_path: Path, snapshot_dir: Path | None) -> str:
    if snapshot_dir is None:
        return "Dry-run only: no files changed; no rollback needed."
    inputs = snapshot_dir / "inputs"
    return (
        "To rollback inputs: stop the solver, then copy "
        f"{inputs}/system {inputs}/constant {inputs}/0 back into {case_path}. "
        "Review processor* directories separately before deleting or restoring decomposed data."
    )


def _request_write_now_and_wait(
    case_path: Path,
    *,
    timeout: float,
    force_stop: bool,
) -> dict[str, Any]:
    before_latest = latest_time(case_path)
    before_jobs = _running_jobs(case_path)
    _request_write_now(case_path)
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if _running_jobs(case_path) == 0:
            return _write_now_evidence(case_path, before_latest, before_jobs, forced_stop=0)
        time.sleep(0.5)
    if _running_jobs(case_path) == 0:
        return _write_now_evidence(case_path, before_latest, before_jobs, forced_stop=0)
    if not force_stop:
        raise ValueError("solver did not stop after writeNow before timeout")
    stopped = knife_service.stop_payload(case_path, all_jobs=True, signal_name="TERM")
    _wait_for_no_jobs(case_path, timeout=timeout)
    return _write_now_evidence(
        case_path,
        before_latest,
        before_jobs,
        forced_stop=int(stopped.get("selected", 0)),
    )


def _write_now_evidence(
    case_path: Path,
    before_latest: str,
    before_jobs: int,
    *,
    forced_stop: int,
) -> dict[str, Any]:
    after_latest = latest_time(case_path)
    after_jobs = _running_jobs(case_path)
    return {
        "acknowledged": after_jobs == 0,
        "jobs_before": before_jobs,
        "jobs_after": after_jobs,
        "latest_time_before": before_latest,
        "latest_time_after": after_latest,
        "forced_stop": forced_stop,
    }


def _request_write_now(case_path: Path) -> None:
    control_dict = case_path / "system" / "controlDict"
    if not apply_assignment_or_write(case_path, control_dict, ["stopAt"], "writeNow"):
        raise ValueError("failed to set system/controlDict:stopAt writeNow")


def _wait_for_no_jobs(case_path: Path, *, timeout: float) -> None:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if _running_jobs(case_path) == 0:
            return
        time.sleep(0.5)
    raise ValueError("solver jobs remained running after TERM fallback")


def _running_jobs(case_path: Path) -> int:
    try:
        return int(knife_service.current_payload(case_path, live=True).get("jobs_running", 0))
    except (OSError, RuntimeError, ValueError, TypeError):
        payload = watch_service.jobs_payload(case_path, include_all=False, kind="solver")
        return int(payload.get("count", 0))


def _run_tool_step(
    case_path: Path,
    steps: list[dict[str, Any]],
    step: str,
    command: list[str],
) -> None:
    result = run_ops.execute_case_command(
        case_path,
        " ".join(command),
        command,
        background=False,
    )
    if int(result.returncode) != 0:
        raise ValueError(result.stderr or result.stdout or f"{command[0]} failed")
    _mark_step(steps, step, "done", returncode=result.returncode)


def _clean_processor_dirs(
    case_path: Path,
    steps: list[dict[str, Any]],
    *,
    enabled: bool,
) -> None:
    if not enabled:
        _mark_step(steps, "clean-processors", "skipped")
        return
    removed = []
    for path in _processor_dirs(case_path):
        shutil.rmtree(path)
        removed.append(path.name)
    _mark_step(steps, "clean-processors", "done", removed=removed)


def _require_decomposed_case(processor_dirs: list[Path]) -> None:
    if processor_dirs:
        return
    raise ValueError(
        "parallel resize requires existing processor* directories; "
        "decompose the case first",
    )


def _set_subdomains(decompose_dict: Path, to_ranks: int) -> None:
    case_path = decompose_dict.parent.parent
    ok = apply_assignment_or_write(
        case_path,
        decompose_dict,
        ["numberOfSubdomains"],
        str(to_ranks),
    )
    if ok and read_number_of_subdomains(decompose_dict) == to_ranks:
        return
    if _write_subdomains_fallback(decompose_dict, to_ranks):
        return
    if not ok:
        raise ValueError("failed to update system/decomposeParDict:numberOfSubdomains")
    raise ValueError("system/decomposeParDict:numberOfSubdomains did not round-trip")


def _write_subdomains_fallback(decompose_dict: Path, to_ranks: int) -> bool:
    try:
        text = decompose_dict.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    replacement = rf"\g<1>\g<prefix>{to_ranks}\g<suffix>"
    if _SUBDOMAINS_RE.search(text):
        updated = _SUBDOMAINS_RE.sub(replacement, text)
    else:
        updated = f"{text.rstrip()}\nnumberOfSubdomains {to_ranks};\n"
    try:
        decompose_dict.write_text(updated, encoding="utf-8")
    except OSError:
        return False
    return _read_subdomains_any(decompose_dict) == to_ranks


def _read_subdomains_any(decompose_dict: Path) -> int | None:
    value = read_number_of_subdomains(decompose_dict)
    if value is not None:
        return value
    try:
        text = decompose_dict.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    matches = list(_SUBDOMAINS_RE.finditer(text))
    if not matches:
        return None
    try:
        return int(float(matches[-1].group("value")))
    except ValueError:
        return None


def _resume_from_latest(case_path: Path) -> None:
    control_dict = case_path / "system" / "controlDict"
    latest = latest_time(case_path)
    if latest in {"", "0", "0.0"}:
        latest = "0"
    if not set_start_from_latest(control_dict, latest):
        raise ValueError("failed to set startFrom latestTime")
    if not apply_assignment_or_write(case_path, control_dict, ["stopAt"], "endTime"):
        raise ValueError("failed to restore stopAt endTime")


def _processor_dirs(case_path: Path) -> list[Path]:
    return sorted(
        path
        for path in case_path.iterdir()
        if path.is_dir() and path.name.startswith("processor") and path.name[9:].isdigit()
    )


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _mark_step(
    steps: list[dict[str, Any]],
    name: str,
    status: str,
    **extra: Any,
) -> None:
    for row in steps:
        if row["step"] == name:
            row["status"] = status
            row.update(extra)
            return


def _mark_first_pending_failed(steps: list[dict[str, Any]], error: str) -> None:
    for row in steps:
        if row.get("status") == "pending":
            row["status"] = "failed"
            row["error"] = error
            return
