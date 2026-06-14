from __future__ import annotations

from pathlib import Path
from typing import cast

from ofti.tools import case_status_service, knife_service, process_scan_service
from ofti.tools.cli_tools import knife


def test_knife_scan_wrapper_delegates_to_service(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _scan(
        case_path: Path,
        solver: str | None,
        *,
        tracked_pids: set[int],
        proc_root: Path = Path("/proc"),
        include_tracked: bool = False,
        require_case_target: bool = True,
    ) -> list[dict[str, object]]:
        seen["case"] = case_path
        seen["solver"] = solver
        seen["tracked"] = tracked_pids
        seen["proc_root"] = proc_root
        seen["include_tracked"] = include_tracked
        seen["require_case_target"] = require_case_target
        return [{"pid": 123}]

    monkeypatch.setattr(process_scan_service, "scan_proc_solver_processes", _scan)
    rows = knife._scan_proc_solver_processes(
        Path("case"),
        "simpleFoam",
        tracked_pids={7},
        proc_root=Path("proc"),
        include_tracked=True,
        require_case_target=False,
    )
    assert rows == [{"pid": 123}]
    assert seen["solver"] == "simpleFoam"
    assert seen["tracked"] == {7}
    assert seen["proc_root"] == Path("proc")
    assert seen["include_tracked"] is True
    assert seen["require_case_target"] is False


def test_knife_current_payload_delegates_to_case_status_service(
    monkeypatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    seen: dict[str, object] = {}

    def _payload(case_path: Path, **kwargs: object) -> dict[str, object]:
        seen["case"] = case_path
        seen["kwargs"] = kwargs
        return {"case": str(case_path), "jobs_running": 0, "untracked_processes": []}

    monkeypatch.setattr(case_status_service, "current_payload", _payload)
    payload = knife.current_payload(case)
    assert payload["jobs_running"] == 0
    assert seen["case"] == case.resolve()
    kwargs = cast("dict[str, object]", seen["kwargs"])
    assert callable(kwargs["resolve_solver_name_fn"])
    assert callable(kwargs["refresh_jobs_fn"])
    assert callable(kwargs["running_job_pids_fn"])
    assert callable(kwargs["scan_proc_solver_processes_fn"])


def test_knife_status_payload_delegates_to_case_status_service(
    monkeypatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    seen: dict[str, object] = {}

    def _payload(case_path: Path, **kwargs: object) -> dict[str, object]:
        seen["case"] = case_path
        seen["kwargs"] = kwargs
        return {"case": str(case_path), "running": True, "jobs_running": 1}

    monkeypatch.setattr(case_status_service, "status_payload", _payload)
    payload = knife.status_payload(case)
    assert payload["running"] is True
    assert payload["jobs_running"] == 1
    assert seen["case"] == case.resolve()
    kwargs = cast("dict[str, object]", seen["kwargs"])
    assert callable(kwargs["resolve_solver_name_fn"])
    assert callable(kwargs["refresh_jobs_fn"])
    assert callable(kwargs["running_job_pids_fn"])
    assert callable(kwargs["scan_proc_solver_processes_fn"])
    assert callable(kwargs["runtime_control_snapshot_fn"])
    assert callable(kwargs["latest_solver_job_fn"])
    assert callable(kwargs["solver_status_text_fn"])
    assert callable(kwargs["latest_time_fn"])


def test_knife_stop_untracked_uses_launcher_group_when_safe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    rows = [
        {
            "pid": 700,
            "role": "launcher",
            "case": str(case.resolve()),
            "solver": "simpleFoam",
            "solver_pids": [701, 702],
        },
        {"pid": 701, "role": "solver", "case": str(case.resolve()), "launcher_pid": 700},
        {"pid": 702, "role": "solver", "case": str(case.resolve()), "launcher_pid": 700},
    ]
    killed: list[int] = []
    killed_groups: list[int] = []

    monkeypatch.setattr("ofti.tools.knife_service.refresh_jobs", lambda _case: [])
    monkeypatch.setattr(
        process_scan_service,
        "scan_proc_solver_processes",
        lambda *_args, **_kwargs: rows,
    )
    monkeypatch.setattr(knife_service.os, "getpgid", lambda _pid: 700)
    monkeypatch.setattr(knife_service.os, "kill", lambda pid, _sig: killed.append(pid))
    monkeypatch.setattr(knife_service.os, "killpg", lambda pgid, _sig: killed_groups.append(pgid))

    payload = knife_service._stop_untracked_solver_processes(case, signal_name="TERM")

    assert killed_groups == [700]
    assert killed == []
    assert payload["selected"] == 1
    assert payload["stopped"][0]["method"] == "process_group"
    assert payload["solver_pids"] == []


def test_knife_stop_untracked_signals_ranks_when_launcher_group_unsafe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    rows = [
        {"pid": 800, "role": "launcher", "case": str(case.resolve()), "solver": "simpleFoam"},
        {"pid": 801, "role": "solver", "case": str(case.resolve()), "launcher_pid": 800},
        {"pid": 802, "role": "solver", "case": str(case.resolve()), "launcher_pid": 800},
    ]
    killed: list[int] = []
    killed_groups: list[int] = []

    monkeypatch.setattr("ofti.tools.knife_service.refresh_jobs", lambda _case: [])
    monkeypatch.setattr(
        process_scan_service,
        "scan_proc_solver_processes",
        lambda *_args, **_kwargs: rows,
    )
    monkeypatch.setattr(knife_service.os, "getpgid", lambda _pid: 12345)
    monkeypatch.setattr(knife_service.os, "kill", lambda pid, _sig: killed.append(pid))
    monkeypatch.setattr(knife_service.os, "killpg", lambda pgid, _sig: killed_groups.append(pgid))

    payload = knife_service._stop_untracked_solver_processes(case, signal_name="TERM")

    assert killed_groups == []
    assert killed == [800, 801, 802]
    assert payload["selected"] == 3
    assert [row["pid"] for row in payload["stopped"]] == [800, 801, 802]
    assert payload["solver_pids"] == [801, 802]


def test_knife_current_scope_payload_tree_scan_uses_proc_scope(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    case = root / "caseA"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "ofti.tools.knife_service.refresh_jobs",
        lambda _case: [{"pid": 10, "status": "running", "name": "simpleFoam"}],
    )

    def _scan(
        case_path: Path,
        solver: str | None,
        *,
        tracked_pids: set[int],
        require_case_target: bool = True,
        **_kwargs: object,
    ) -> list[dict[str, object]]:
        seen["case_path"] = case_path
        seen["solver"] = solver
        seen["tracked"] = tracked_pids
        seen["require_case_target"] = require_case_target
        return []

    monkeypatch.setattr("ofti.tools.knife_service._scan_proc_solver_processes", _scan)
    payload = knife.current_scope_payload(root, live=True, recursive=True)
    assert payload["scope"] == "tree"
    assert seen["case_path"] == root.resolve()
    assert seen["solver"] is None
    assert seen["tracked"] == {10}
    assert seen["require_case_target"] is False
