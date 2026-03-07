from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def runtime_criteria_lines(criteria: list[Mapping[str, Any]]) -> list[str]:
    if not criteria:
        return ["criteria=none"]
    lines = ["criteria:"]
    for row in criteria:
        lines.append(
            f"- {row.get('key')}: status={row.get('status')} "
            f"value={row.get('live_value')} delta={row.get('live_delta')} "
            f"tolerance={row.get('tolerance')} eta={row.get('eta_seconds')} "
            f"unmet_reason={row.get('unmet_reason')}",
        )
    return lines


def case_status_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = [
        f"case={payload['case']}",
        f"latest_time={payload['latest_time']}",
        f"latest_iteration={payload.get('latest_iteration')}",
        f"latest_deltaT={payload.get('latest_delta_t')}",
        f"sec_per_iter={payload.get('sec_per_iter')}",
    ]
    if payload.get("solver_error"):
        lines.append(f"solver_error={payload['solver_error']}")
    else:
        lines.append(f"solver={payload.get('solver')}")
        lines.append(f"solver_status={payload.get('solver_status') or 'not tracked'}")
    rtc = payload.get("run_time_control", {})
    lines.append(
        "runtime_control="
        f"criteria:{len(rtc.get('criteria', []))} "
        f"pass:{rtc.get('passed', 0)} fail:{rtc.get('failed', 0)} "
        f"unknown:{rtc.get('unknown', 0)}",
    )
    lines.extend(runtime_criteria_lines(rtc.get("criteria", [])))
    lines.append(f"eta_to_criteria_start={payload.get('eta_seconds_to_criteria_start')}")
    lines.append(f"eta_to_end_time={payload.get('eta_seconds_to_end_time')}")
    lines.append(
        f"log_path={payload.get('log_path')} "
        f"fresh={payload.get('log_fresh')} running={payload.get('running')}",
    )
    tracked = payload.get("tracked_solver_processes", [])
    untracked = payload.get("untracked_solver_processes", [])
    if tracked:
        lines.append(f"tracked_solver_processes={len(tracked)}")
    if untracked:
        lines.append(f"untracked_solver_processes={len(untracked)}")
    lines.append(f"jobs_running={payload['jobs_running']} jobs_total={payload['jobs_total']}")
    return lines
