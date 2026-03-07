from __future__ import annotations

from pathlib import Path

from ofti.tools import case_status_service as svc


def test_current_payload_relaxes_proc_target_when_solver_is_unknown(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    calls: list[bool] = []

    def _scan(
        _case: Path,
        _solver: str | None,
        *,
        tracked_pids: set[int],
        require_case_target: bool = True,
    ) -> list[svc.SolverProcessRow]:
        assert tracked_pids == set()
        calls.append(require_case_target)
        if require_case_target:
            return []
        return [
            {
                "pid": 404,
                "ppid": 1,
                "solver": "hy2Foam",
                "role": "solver",
                "tracked": False,
                "command": "hy2Foam -parallel",
            },
        ]

    payload = svc.current_payload(
        case,
        resolve_solver_name_fn=lambda _case: (None, "system/controlDict not found"),
        refresh_jobs_fn=lambda _case: [],
        running_job_pids_fn=lambda _jobs: [],
        scan_proc_solver_processes_fn=_scan,
    )
    assert payload["jobs_running"] == 1
    assert payload["untracked_processes"][0]["pid"] == 404
    assert calls == [True, False]


def test_status_payload_uses_runtime_and_live_process_data(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    jobs = [{"id": "1", "name": "hy2Foam", "pid": 42, "status": "running"}]

    payload = svc.status_payload(
        case,
        resolve_solver_name_fn=lambda _case: ("hy2Foam", None),
        refresh_jobs_fn=lambda _case: jobs,
        running_job_pids_fn=lambda _jobs: [42],
        scan_proc_solver_processes_fn=lambda *_a, **_k: [
            {
                "pid": 42,
                "ppid": 1,
                "solver": "hy2Foam",
                "role": "solver",
                "tracked": True,
                "command": "hy2Foam -parallel",
            },
            {
                "pid": 43,
                "ppid": 1,
                "solver": "hy2Foam",
                "role": "solver",
                "tracked": False,
                "command": "hy2Foam -parallel",
            },
        ],
        runtime_control_snapshot_fn=lambda _case, _solver: {
            "latest_time": None,
            "latest_iteration": 100,
            "latest_delta_t": 1e-9,
            "sec_per_iter": 0.1,
            "run_time_control": {
                "end_time": 1.0,
                "criteria_start": 0.2,
                "criteria": [],
                "passed": 0,
                "failed": 0,
                "unknown": 0,
            },
            "eta_to_criteria_start": 1.0,
            "eta_to_end_time": 4.0,
            "log_path": str(case / "log.hy2Foam"),
            "log_fresh": True,
            "residual_fields": [],
        },
        latest_solver_job_fn=lambda _case, _solver: {"status": "running"},
        solver_status_text_fn=lambda _summary: "running",
        latest_time_fn=lambda _case: 0.123,
    )

    assert payload["solver_status"] == "running"
    assert payload["latest_time"] == 0.123
    assert payload["running"] is True
    assert payload["jobs_running"] == 1
    assert len(payload["tracked_solver_processes"]) == 1
    assert len(payload["untracked_solver_processes"]) == 1


def test_status_payload_forwards_lightweight_runtime_options(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    seen: dict[str, object] = {}

    def _snapshot(_case: Path, _solver: str | None, **kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {
            "latest_time": 0.1,
            "latest_iteration": 1,
            "latest_delta_t": 1e-9,
            "sec_per_iter": 0.2,
            "run_time_control": {
                "end_time": 1.0,
                "criteria_start": None,
                "criteria": [],
                "passed": 0,
                "failed": 0,
                "unknown": 0,
            },
            "eta_to_criteria_start": None,
            "eta_to_end_time": None,
            "log_path": str(case / "log.hy2Foam"),
            "log_fresh": False,
            "residual_fields": [],
        }

    payload = svc.status_payload(
        case,
        resolve_solver_name_fn=lambda _case: ("hy2Foam", None),
        refresh_jobs_fn=lambda _case: [],
        running_job_pids_fn=lambda _jobs: [],
        scan_proc_solver_processes_fn=lambda *_a, **_k: [],
        runtime_control_snapshot_fn=_snapshot,
        latest_solver_job_fn=lambda _case, _solver: None,
        solver_status_text_fn=lambda _summary: "",
        latest_time_fn=lambda _case: None,
        lightweight=True,
        tail_bytes=1234,
    )
    assert payload["latest_time"] == 0.1
    assert seen["lightweight"] is True
    assert seen["max_log_bytes"] == 1234
