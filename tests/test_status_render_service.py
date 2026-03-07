from __future__ import annotations

from ofti.tools import status_render_service as svc


def test_runtime_criteria_lines_empty_and_non_empty() -> None:
    assert svc.runtime_criteria_lines([]) == ["criteria=none"]
    lines = svc.runtime_criteria_lines(
        [
            {
                "key": "residualTolerance",
                "status": "fail",
                "live_value": 0.1,
                "live_delta": 0.02,
                "tolerance": 0.01,
                "eta_seconds": 12.0,
                "unmet_reason": "window",
            },
        ],
    )
    assert lines[0] == "criteria:"
    assert "residualTolerance" in lines[1]
    assert "unmet_reason=window" in lines[1]


def test_case_status_lines_summary() -> None:
    payload = {
        "case": "/case",
        "latest_time": 0.1,
        "latest_iteration": 10,
        "latest_delta_t": 1e-9,
        "sec_per_iter": 0.2,
        "solver_error": None,
        "solver": "simpleFoam",
        "solver_status": "running",
        "run_time_control": {"criteria": [], "passed": 0, "failed": 0, "unknown": 0},
        "eta_seconds_to_criteria_start": None,
        "eta_seconds_to_end_time": None,
        "log_path": "/case/log.simpleFoam",
        "log_fresh": True,
        "running": True,
        "tracked_solver_processes": [{"pid": 1}],
        "untracked_solver_processes": [{"pid": 2}],
        "jobs_running": 1,
        "jobs_total": 2,
    }
    lines = svc.case_status_lines(payload)
    assert any("runtime_control=criteria:0 pass:0 fail:0 unknown:0" in line for line in lines)
    assert any("tracked_solver_processes=1" in line for line in lines)
    assert any("untracked_solver_processes=1" in line for line in lines)
