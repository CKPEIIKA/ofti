from __future__ import annotations

from pathlib import Path

from ofti.tools import job_control_service as svc


def test_signal_and_selection_helpers() -> None:
    assert int(svc.signal_by_name("TERM")) > 0
    jobs = [
        {"id": "1", "name": "a", "status": "running"},
        {"id": "2", "name": "b", "status": "paused"},
    ]
    assert [row["id"] for row in svc.select_jobs(jobs, statuses={"running"}, job_id=None, name=None, all_jobs=False)] == ["1"]
    assert [row["id"] for row in svc.select_jobs(jobs, statuses={"running", "paused"}, job_id=None, name=None, all_jobs=True)] == ["1", "2"]


def test_stop_jobs_transitions_and_failures(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    jobs = [
        {"id": "1", "name": "solver", "pid": 11, "status": "running"},
        {"id": "2", "name": "solver", "pid": "bad", "status": "running"},
        {"id": "3", "name": "solver", "pid": 33, "status": "running"},
    ]
    killed: list[int] = []
    finished: list[tuple[str, str]] = []

    def _kill(pid: int, _sig: int) -> None:
        killed.append(pid)
        if pid == 33:
            raise OSError("gone")

    def _finish(_case: Path, job_id: str, status: str, _rc: int | None) -> None:
        finished.append((job_id, status))

    payload = svc.stop_jobs(
        case,
        jobs,
        job_id=None,
        name=None,
        all_jobs=True,
        signal_name="TERM",
        kill_fn=_kill,
        finish_job_fn=_finish,
    )
    assert payload["selected"] == 3
    assert [row["id"] for row in payload["stopped"]] == ["1"]
    assert {row["id"] for row in payload["failed"]} == {"2", "3"}
    assert ("1", "stopped") in finished
    assert ("3", "missing") in finished
    assert killed == [11, 33]


def test_stop_jobs_prefers_detached_process_group(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    jobs = [
        {
            "id": "1",
            "name": "simpleFoam-launcher",
            "pid": 100,
            "launcher_pid": 100,
            "solver_pids": [101, 102],
            "status": "running",
            "detached": True,
        },
    ]
    killed: list[int] = []
    killed_groups: list[int] = []
    finished: list[tuple[str, str]] = []

    payload = svc.stop_jobs(
        case,
        jobs,
        job_id=None,
        name=None,
        all_jobs=True,
        signal_name="TERM",
        kill_fn=lambda pid, _sig: killed.append(pid),
        finish_job_fn=lambda _case, job_id, status, _rc: finished.append((job_id, status)),
        killpg_fn=lambda pgid, _sig: killed_groups.append(pgid),
        getpgid_fn=lambda _pid: 100,
    )

    assert killed == []
    assert killed_groups == [100]
    assert payload["stopped"][0]["method"] == "process_group"
    assert payload["stopped"][0]["pgid"] == 100
    assert payload["stopped"][0]["pids"] == [100, 101, 102]
    assert finished == [("1", "stopped")]


def test_stop_jobs_prefers_launcher_group_for_recovered_mpi_job(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    jobs = [
        {
            "id": "1",
            "name": "simpleFoam-launcher",
            "pid": 401,
            "launcher_pid": 400,
            "solver_pids": [401, 402],
            "status": "running",
            "detached": True,
        },
    ]
    killed: list[int] = []
    killed_groups: list[int] = []
    pgid_lookups: list[int] = []

    def _getpgid(pid: int) -> int:
        pgid_lookups.append(pid)
        return {400: 400, 401: 12345, 402: 12345}[pid]

    payload = svc.stop_jobs(
        case,
        jobs,
        job_id=None,
        name=None,
        all_jobs=True,
        signal_name="TERM",
        kill_fn=lambda pid, _sig: killed.append(pid),
        finish_job_fn=lambda *_a: None,
        killpg_fn=lambda pgid, _sig: killed_groups.append(pgid),
        getpgid_fn=_getpgid,
    )

    assert pgid_lookups == [400]
    assert killed == []
    assert killed_groups == [400]
    assert payload["stopped"][0]["pid"] == 400
    assert payload["stopped"][0]["method"] == "process_group"
    assert payload["stopped"][0]["pids"] == [400, 401, 402]


def test_stop_jobs_signals_launcher_and_ranks_when_launcher_group_unsafe(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    jobs = [
        {
            "id": "1",
            "name": "simpleFoam-launcher",
            "pid": 501,
            "launcher_pid": 500,
            "solver_pids": [501, 502],
            "status": "running",
            "detached": False,
        },
    ]
    killed: list[int] = []
    killed_groups: list[int] = []

    payload = svc.stop_jobs(
        case,
        jobs,
        job_id=None,
        name=None,
        all_jobs=True,
        signal_name="TERM",
        kill_fn=lambda pid, _sig: killed.append(pid),
        finish_job_fn=lambda *_a: None,
        killpg_fn=lambda pgid, _sig: killed_groups.append(pgid),
        getpgid_fn=lambda _pid: 12345,
    )

    assert killed_groups == []
    assert killed == [500, 501, 502]
    assert payload["stopped"][0]["pid"] == 500
    assert payload["stopped"][0]["method"] == "processes"
    assert payload["stopped"][0]["pids"] == [500, 501, 502]


def test_stop_jobs_avoids_foreground_shell_group_for_adopted_mpi(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    jobs = [
        {
            "id": "1",
            "name": "simpleFoam-launcher",
            "pid": 200,
            "launcher_pid": 200,
            "solver_pids": [201, 202],
            "status": "running",
            "detached": False,
        },
    ]
    killed: list[int] = []
    killed_groups: list[int] = []

    payload = svc.stop_jobs(
        case,
        jobs,
        job_id=None,
        name=None,
        all_jobs=True,
        signal_name="TERM",
        kill_fn=lambda pid, _sig: killed.append(pid),
        finish_job_fn=lambda *_a: None,
        killpg_fn=lambda pgid, _sig: killed_groups.append(pgid),
        getpgid_fn=lambda _pid: 12345,
    )

    assert killed_groups == []
    assert killed == [200, 201, 202]
    assert payload["stopped"][0]["method"] == "processes"
    assert payload["stopped"][0]["pids"] == [200, 201, 202]


def test_stop_jobs_falls_back_when_group_signal_fails(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    jobs = [
        {
            "id": "1",
            "name": "simpleFoam-launcher",
            "pid": 300,
            "launcher_pid": 300,
            "solver_pids": [301],
            "status": "running",
            "detached": True,
        },
    ]
    killed: list[int] = []

    def _killpg(_pgid: int, _sig: int) -> None:
        raise OSError("group gone")

    payload = svc.stop_jobs(
        case,
        jobs,
        job_id=None,
        name=None,
        all_jobs=True,
        signal_name="TERM",
        kill_fn=lambda pid, _sig: killed.append(pid),
        finish_job_fn=lambda *_a: None,
        killpg_fn=_killpg,
        getpgid_fn=lambda _pid: 300,
    )

    assert killed == [300, 301]
    assert payload["stopped"][0]["method"] == "processes"


def test_pause_resume_jobs_state_callbacks(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    jobs = [{"id": "1", "name": "solver", "pid": 11, "status": "running"}]
    status_updates: list[tuple[str, str]] = []

    paused = svc.pause_jobs(
        case,
        jobs,
        job_id=None,
        name=None,
        all_jobs=True,
        kill_fn=lambda _pid, _sig: None,
        finish_job_fn=lambda *_a, **_k: None,
        set_status_fn=lambda _case, job_id, status: status_updates.append((job_id, status)),
    )
    assert paused["selected"] == 1
    assert status_updates[-1] == ("1", "paused")

    jobs_paused = [{"id": "1", "name": "solver", "pid": 11, "status": "paused"}]
    resumed = svc.resume_jobs(
        case,
        jobs_paused,
        job_id=None,
        name=None,
        all_jobs=True,
        kill_fn=lambda _pid, _sig: None,
        finish_job_fn=lambda *_a, **_k: None,
        set_status_fn=lambda _case, job_id, status: status_updates.append((job_id, status)),
    )
    assert resumed["selected"] == 1
    assert status_updates[-1] == ("1", "running")


def test_set_job_status_updates_running_fields(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    state: list[dict[str, object]] = [
        {"id": "1", "status": "paused", "ended_at": 1.0, "returncode": 2},
    ]

    def _load(_path: Path) -> list[dict[str, object]]:
        return state

    def _save(_path: Path, payload: list[dict[str, object]]) -> None:
        state[:] = payload

    svc.set_job_status(case, "1", "running", load_jobs_fn=_load, save_jobs_fn=_save)
    assert state[0]["status"] == "running"
    assert state[0]["ended_at"] is None
    assert state[0]["returncode"] is None
