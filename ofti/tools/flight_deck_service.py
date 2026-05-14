from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ofti.foamlib import adapter as foamlib_integration
from ofti.tools import knife_service


def flight_deck_payload(case_path: Path) -> dict[str, Any]:
    status = knife_service.status_payload(case_path, lightweight=True, tail_bytes=256 * 1024)
    current = knife_service.current_payload(case_path, live=True)
    criteria = knife_service.criteria_payload(case_path)
    control = _control_dict_snapshot(case_path)
    return {
        "case": str(case_path),
        "status": status,
        "current": current,
        "criteria": criteria,
        "control": control,
        "runtime_queue": _runtime_queue(status, current, control),
        "actions": [
            {"key": "s", "action": "safe stop", "risk": "low"},
            {"key": "p", "action": "pause tracked solver", "risk": "medium"},
            {"key": "u", "action": "resume tracked solver", "risk": "low"},
            {"key": "a", "action": "adopt untracked solver", "risk": "low"},
        ],
    }


def _control_dict_snapshot(case_path: Path) -> dict[str, Any]:
    path = case_path / "system" / "controlDict"
    keys = ("application", "startFrom", "startTime", "stopAt", "endTime", "deltaT", "writeInterval")
    values = {key: _read_control_entry(path, key) for key in keys}
    return {
        "path": "system/controlDict",
        "exists": path.is_file(),
        "values": values,
        "runtime_modifiable": _runtime_modifiable(path),
    }


def _runtime_queue(
    status: dict[str, Any],
    current: dict[str, Any],
    control: dict[str, Any],
) -> list[dict[str, Any]]:
    running = bool(status.get("running") or int(current.get("jobs_running") or 0) > 0)
    jobs = list(current.get("jobs") or [])
    tracked_running = sum(1 for job in jobs if str(dict(job).get("status")) == "running")
    tracked_paused = sum(1 for job in jobs if str(dict(job).get("status")) == "paused")
    untracked = len(list(current.get("untracked_processes") or []))
    values = dict(control.get("values") or {})
    stop_at = values.get("stopAt") or "endTime"
    delta_t = values.get("deltaT") or "unknown"
    end_time = values.get("endTime") or "unknown"
    runtime_modifiable = control.get("runtime_modifiable")
    if runtime_modifiable is True:
        runtime_reload = "yes"
    elif runtime_modifiable is False:
        runtime_reload = "no"
    else:
        runtime_reload = "unknown"
    return [
        {
            "key": "safe-stop",
            "status": "ready" if running else "idle",
            "action": "safe stop",
            "target": "system/controlDict:stopAt",
            "change": f"{stop_at} -> writeNow",
            "requires": "running solver; dictionary reread",
            "confirm": "wait for latest write and solver exit",
            "risk": "low",
            "diff": _assignment_diff("stopAt", stop_at, "writeNow"),
        },
        {
            "key": "write-now",
            "status": "ready" if running else "idle",
            "action": "write latest time",
            "target": "system/controlDict:stopAt",
            "change": f"{stop_at} -> writeNow",
            "requires": "running solver; snapshot first if preserving run state",
            "confirm": "watch log for write and restore stopAt if continuing",
            "risk": "medium",
            "diff": _assignment_diff("stopAt", stop_at, "writeNow"),
        },
        {
            "key": "deltaT",
            "status": "needs-value" if running else "idle",
            "action": "change deltaT",
            "target": "system/controlDict:deltaT",
            "change": f"{delta_t} -> <prompt>",
            "requires": f"runtimeModifiable={runtime_reload}; solver supports reread",
            "confirm": "watch log/next timestep for new deltaT",
            "risk": "medium",
            "diff": _assignment_diff("deltaT", delta_t, "<new-deltaT>"),
        },
        {
            "key": "endTime",
            "status": "needs-value" if running else "idle",
            "action": "change endTime",
            "target": "system/controlDict:endTime",
            "change": f"{end_time} -> <prompt>",
            "requires": f"runtimeModifiable={runtime_reload}; solver supports reread",
            "confirm": "watch status ETA/end time refresh",
            "risk": "low",
            "diff": _assignment_diff("endTime", end_time, "<new-endTime>"),
        },
        {
            "key": "pause",
            "status": "ready" if tracked_running else "unavailable",
            "action": "pause tracked solver",
            "target": "tracked solver pids",
            "change": "SIGSTOP tracked jobs",
            "requires": f"{tracked_running} tracked running job(s)",
            "confirm": "registry status becomes paused",
            "risk": "medium",
            "diff": [],
        },
        {
            "key": "resume",
            "status": "ready" if tracked_paused else "unavailable",
            "action": "resume tracked solver",
            "target": "tracked solver pids",
            "change": "SIGCONT paused jobs",
            "requires": f"{tracked_paused} tracked paused job(s)",
            "confirm": "registry status becomes running",
            "risk": "low",
            "diff": [],
        },
        {
            "key": "adopt",
            "status": "ready" if untracked else "unavailable",
            "action": "adopt untracked solver",
            "target": "live OpenFOAM pids",
            "change": "register untracked process",
            "requires": f"{untracked} untracked solver process(es)",
            "confirm": "job registry contains adopted pid",
            "risk": "low",
            "diff": [],
        },
    ]


def _read_control_entry(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    if foamlib_integration.available() and foamlib_integration.is_foam_file(path):
        try:
            return foamlib_integration.read_entry(path, key).strip().rstrip(";") or None
        except Exception:
            pass
    return _read_control_entry_fallback(path, key)


def _read_control_entry_fallback(path: Path, key: str) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s+([^;]+);", text)
    return match.group(1).strip() if match else None


def _runtime_modifiable(path: Path) -> bool | None:
    value = _read_control_entry(path, "runtimeModifiable")
    if value is None:
        return None
    lowered = value.lower()
    if lowered in {"true", "yes", "on", "1"}:
        return True
    if lowered in {"false", "no", "off", "0"}:
        return False
    return None


def _assignment_diff(key: str, old: str, new: str) -> list[str]:
    return [
        "--- current system/controlDict",
        "+++ proposed system/controlDict",
        f"-{key} {old};",
        f"+{key} {new};",
    ]
