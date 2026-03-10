from __future__ import annotations

from pathlib import Path

from ofti.tools import process_scan_service as svc


def _make_case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "system" / "controlDict").write_text("application hy2Foam;\n")
    return path


def _write_proc_entry(
    proc_root: Path,
    *,
    pid: int,
    ppid: int,
    cmdline: bytes,
    cwd: Path | None,
    comm: str | None = None,
) -> Path:
    proc_dir = proc_root / str(pid)
    proc_dir.mkdir()
    stat_tail = f"S {ppid} 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"
    (proc_dir / "stat").write_text(f"{pid} (cmd) {stat_tail}\n")
    (proc_dir / "cmdline").write_bytes(cmdline)
    if comm is not None:
        (proc_dir / "comm").write_text(comm)
    if cwd is not None:
        (proc_dir / "cwd").symlink_to(cwd, target_is_directory=True)
    return proc_dir


def test_running_job_pids_filters_invalid_values() -> None:
    rows = svc.running_job_pids([{"pid": 10}, {"pid": 0}, {"pid": "x"}, {"pid": -4}, {"pid": 5}])
    assert rows == [10, 5]


def test_scan_proc_solver_processes_filters_tracked(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc_entry(
        proc_root,
        pid=100,
        ppid=1,
        cmdline=b"mpirun\x00-case\x00.\x00hy2Foam\x00",
        cwd=case,
    )
    _write_proc_entry(
        proc_root,
        pid=101,
        ppid=100,
        cmdline=b"hy2Foam\x00-parallel\x00-case\x00.\x00",
        cwd=case,
    )

    rows = svc.scan_proc_solver_processes(
        case,
        "hy2Foam",
        tracked_pids={101},
        proc_root=proc_root,
        include_tracked=False,
    )
    assert {int(row["pid"]) for row in rows} == {100}
    assert rows[0]["launcher_pid"] == 100
    assert rows[0]["solver_pids"] == [101]

    rows_all = svc.scan_proc_solver_processes(
        case,
        "hy2Foam",
        tracked_pids={101},
        proc_root=proc_root,
        include_tracked=True,
    )
    assert {int(row["pid"]) for row in rows_all} == {100, 101}
    solver_row = next(row for row in rows_all if int(row["pid"]) == 101)
    assert solver_row["launcher_pid"] == 100


def test_launcher_graph_helpers_scope_case(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    other = _make_case(tmp_path / "other")
    table = {
        10: svc.ProcEntry(pid=10, ppid=1, args=["mpirun", "-case", "."], cwd=case),
        11: svc.ProcEntry(pid=11, ppid=10, args=["hy2Foam", "-parallel"], cwd=case),
        20: svc.ProcEntry(pid=20, ppid=1, args=["mpirun", "-case", "."], cwd=other),
    }
    launchers = svc.launcher_pids_for_case(table, "hy2foam", case)
    assert launchers == {10}
    assert svc.launcher_has_solver_descendant(10, table, "hy2foam") is True
    assert svc.has_ancestor(11, {10}, table) is True


def test_scan_proc_solver_processes_infers_case_from_processor_cwd(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "repo" / "caseA")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    processor0 = case / "processor0"
    processor0.mkdir()
    _write_proc_entry(
        proc_root,
        pid=220,
        ppid=1,
        cmdline=b"hy2Foam\x00-parallel\x00",
        cwd=processor0,
    )

    rows = svc.scan_proc_solver_processes(
        case.parent,
        None,
        tracked_pids=set(),
        proc_root=proc_root,
        require_case_target=True,
    )
    assert len(rows) == 1
    assert rows[0]["case"] == str(case.resolve())
    assert rows[0]["discovery_source"] in {"procfs", "launcher"}
    assert rows[0]["discovery_error"] == ""


def test_read_proc_args_falls_back_to_comm(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    proc_dir = _write_proc_entry(
        proc_root,
        pid=333,
        ppid=1,
        cmdline=b"",
        cwd=None,
        comm="hy2Foam",
    )
    assert svc.read_proc_args(proc_dir) == ["hy2Foam"]


def test_scan_processes_reports_unknown_case_with_explicit_error(tmp_path: Path) -> None:
    svc._DISCOVERY_CACHE.clear()
    case = _make_case(tmp_path / "case")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc_entry(
        proc_root,
        pid=400,
        ppid=1,
        cmdline=b"hy2Foam\x00-parallel\x00",
        cwd=None,
    )
    rows = svc.scan_proc_solver_processes(
        case,
        None,
        tracked_pids=set(),
        proc_root=proc_root,
        require_case_target=False,
    )
    assert len(rows) == 1
    assert rows[0]["case"] == ""
    assert rows[0]["discovery_source"] == "procfs"
    assert rows[0]["discovery_error"] != ""


def test_scan_processes_infers_case_from_shell_cd_parent(tmp_path: Path) -> None:
    svc._DISCOVERY_CACHE.clear()
    case = _make_case(tmp_path / "case")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc_entry(
        proc_root,
        pid=500,
        ppid=1,
        cmdline=f"bash\x00-lc\x00cd {case} && mpirun -np 6 hy2Foam -parallel\x00".encode(),
        cwd=None,
    )
    _write_proc_entry(
        proc_root,
        pid=501,
        ppid=500,
        cmdline=b"hy2Foam\x00-parallel\x00",
        cwd=None,
    )
    rows = svc.scan_proc_solver_processes(
        case.parent,
        None,
        tracked_pids=set(),
        proc_root=proc_root,
        require_case_target=True,
    )
    assert {row["pid"] for row in rows} == {501}
    assert rows[0]["case"] == str(case.resolve())
    assert rows[0]["launcher_pid"] is None
    assert rows[0]["discovery_source"] in {"procfs", "launcher"}


def test_scan_processes_uses_registry_cache_for_same_pid(tmp_path: Path) -> None:
    svc._DISCOVERY_CACHE.clear()
    case = _make_case(tmp_path / "case")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    proc_dir = _write_proc_entry(
        proc_root,
        pid=700,
        ppid=1,
        cmdline=b"hy2Foam\x00-parallel\x00",
        cwd=case,
    )
    rows = svc.scan_proc_solver_processes(
        case,
        None,
        tracked_pids=set(),
        proc_root=proc_root,
        require_case_target=True,
    )
    assert rows[0]["case"] == str(case.resolve())
    assert rows[0]["discovery_source"] == "procfs"

    (proc_dir / "cwd").unlink()
    rows_cached = svc.scan_proc_solver_processes(
        case,
        None,
        tracked_pids=set(),
        proc_root=proc_root,
        require_case_target=False,
    )
    assert rows_cached[0]["case"] == str(case.resolve())
    assert rows_cached[0]["discovery_source"] == "registry"
