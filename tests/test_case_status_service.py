from __future__ import annotations

from pathlib import Path

from ofti.tools import case_status_service as svc


def test_current_payload_uses_single_scan_path_for_unknown_solver(tmp_path: Path) -> None:
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
                "solver": "simpleFoam",
                "role": "solver",
                "tracked": False,
                "command": "simpleFoam -parallel",
            },
        ]

    payload = svc.current_payload(
        case,
        resolve_solver_name_fn=lambda _case: (None, "system/controlDict not found"),
        refresh_jobs_fn=lambda _case: [],
        running_job_pids_fn=lambda _jobs: [],
        scan_proc_solver_processes_fn=_scan,
    )
    assert payload["jobs_running"] == 0
    assert payload["jobs_registry_running"] == 0
    assert payload["untracked_processes"] == []
    assert calls == [True]

    payload_live = svc.current_payload(
        case,
        resolve_solver_name_fn=lambda _case: (None, "system/controlDict not found"),
        refresh_jobs_fn=lambda _case: [],
        running_job_pids_fn=lambda _jobs: [],
        scan_proc_solver_processes_fn=_scan,
        live=True,
    )
    assert payload_live["jobs_running"] == 1
    assert payload_live["jobs_registry_running"] == 0
    assert payload_live["untracked_processes"][0]["pid"] == 404
    assert calls == [True, False]


def test_status_payload_uses_runtime_and_live_process_data(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    jobs = [{"id": "1", "name": "simpleFoam", "pid": 42, "status": "running"}]

    payload = svc.status_payload(
        case,
        resolve_solver_name_fn=lambda _case: ("simpleFoam", None),
        refresh_jobs_fn=lambda _case: jobs,
        running_job_pids_fn=lambda _jobs: [42],
        scan_proc_solver_processes_fn=lambda *_a, **_k: [
            {
                "pid": 42,
                "ppid": 1,
                "solver": "simpleFoam",
                "role": "solver",
                "tracked": True,
                "command": "simpleFoam -parallel",
            },
            {
                "pid": 43,
                "ppid": 1,
                "solver": "simpleFoam",
                "role": "solver",
                "tracked": False,
                "command": "simpleFoam -parallel",
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
            "log_path": str(case / "log.simpleFoam"),
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
    assert payload["jobs_running"] == 2
    assert payload["jobs_registry_running"] == 1
    assert payload["jobs_tracked_running"] == 1
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
            "log_path": str(case / "log.simpleFoam"),
            "log_fresh": False,
            "residual_fields": [],
        }

    payload = svc.status_payload(
        case,
        resolve_solver_name_fn=lambda _case: ("simpleFoam", None),
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


def test_untracked_running_count_dedupes_solver_under_launcher() -> None:
    rows: list[svc.SolverProcessRow] = [
        {
            "pid": 100,
            "ppid": 1,
            "solver": "simpleFoam",
            "role": "launcher",
            "tracked": False,
            "command": "bash -lc simpleFoam -parallel",
        },
        {
            "pid": 101,
            "ppid": 100,
            "solver": "simpleFoam",
            "role": "solver",
            "tracked": False,
            "launcher_pid": 100,
            "command": "simpleFoam -parallel",
        },
    ]
    assert svc.untracked_running_count(rows) == 1


def test_untracked_running_count_counts_solver_when_launcher_row_missing() -> None:
    rows: list[svc.SolverProcessRow] = [
        {
            "pid": 301,
            "ppid": 1,
            "solver": "simpleFoam",
            "role": "solver",
            "tracked": False,
            "launcher_pid": 300,
            "command": "simpleFoam -parallel",
        },
    ]
    assert svc.untracked_running_count(rows) == 1


def test_canonical_run_rows_collapses_launcher_and_solver_ranks(tmp_path: Path) -> None:
    case = tmp_path / "case"
    active_jobs = [
        {
            "id": "job-1",
            "name": "mpirun-simpleFoam",
            "pid": 100,
            "launcher_pid": 100,
            "solver_pids": [101, 102],
            "status": "running",
            "case_dir": str(case),
        },
    ]
    untracked: list[svc.SolverProcessRow] = [
        {
            "pid": 101,
            "ppid": 100,
            "solver": "simpleFoam",
            "role": "solver",
            "tracked": False,
            "launcher_pid": 100,
            "case": str(case),
            "command": "simpleFoam -parallel",
        },
    ]

    rows = svc.canonical_run_rows(case, active_jobs, untracked)

    assert len(rows) == 1
    assert rows[0]["source"] == "registry"
    assert rows[0]["process_group_pids"] == [100, 101, 102]


def test_canonical_run_rows_hides_untracked_launcher_for_tracked_rank(tmp_path: Path) -> None:
    case = tmp_path / "case"
    active_jobs = [
        {
            "id": "job-1",
            "name": "simpleFoam",
            "pid": 101,
            "launcher_pid": 100,
            "solver_pids": [101],
            "status": "running",
            "case_dir": str(case),
        },
    ]
    untracked: list[svc.SolverProcessRow] = [
        {
            "pid": 100,
            "ppid": 1,
            "solver": "simpleFoam",
            "role": "launcher",
            "tracked": False,
            "launcher_pid": 100,
            "solver_pids": [101],
            "case": str(case),
            "command": "mpirun -np 1 simpleFoam -parallel",
        },
    ]

    rows = svc.canonical_run_rows(case, active_jobs, untracked)

    assert len(rows) == 1
    assert rows[0]["source"] == "registry"
    assert rows[0]["process_group_pids"] == [100, 101]


def test_attach_process_visibility_explains_limited_live_scan() -> None:
    payload: dict[str, object] = {
        "jobs_registry_running": 1,
        "untracked_processes": [],
        "tracked_solver_processes": [],
    }

    svc.attach_process_visibility(payload, "procfs pid 1 is unreadable")

    visibility = payload["process_visibility"]
    assert isinstance(visibility, dict)
    assert visibility["limited"] is True
    assert "registry shows 1 tracked run" in str(visibility["message"])
