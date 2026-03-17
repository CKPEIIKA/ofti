from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from ofti.core import dict_compare
from ofti.core.dict_compare import DictDiff, ValueDiff
from ofti.tools import knife_service
from ofti.tools.cli_tools import knife


def _make_case(path: Path, solver: str = "simpleFoam") -> Path:
    (path / "system").mkdir(parents=True)
    (path / "0").mkdir()
    (path / "system" / "controlDict").write_text(f"application {solver};\n")
    return path


def _write_proc_entry(
    proc_root: Path,
    *,
    pid: int,
    ppid: int,
    cmdline: bytes = b"",
    cwd: Path | None = None,
    stat_tail: str | None = None,
) -> Path:
    proc_dir = proc_root / str(pid)
    proc_dir.mkdir()
    (proc_dir / "cmdline").write_bytes(cmdline)
    if stat_tail is None:
        stat_tail = f"S {ppid} 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"
    (proc_dir / "stat").write_text(f"{pid} (cmd) {stat_tail}\n")
    if cwd is not None:
        (proc_dir / "cwd").symlink_to(cwd, target_is_directory=True)
    return proc_dir


def test_knife_doctor_and_compare_payloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        knife_service,
        "build_case_doctor_report",
        lambda _path: {"lines": ["ok"], "errors": [], "warnings": ["warn"]},
    )
    payload = knife.doctor_payload(case)
    assert payload["lines"] == ["ok"]
    assert knife.doctor_exit_code(payload) == 0
    assert knife.doctor_exit_code({"errors": ["bad"]}) == 1

    monkeypatch.setattr(
        knife_service,
        "compare_case_dicts",
        lambda _l, _r: [
            DictDiff(
                rel_path="system/controlDict",
                missing_in_left=["a"],
                missing_in_right=["b"],
                value_diffs=[ValueDiff(key="application", left="simpleFoam", right="rhoSimpleFoam")],
                kind="dict",
                error=None,
            ),
        ],
    )
    compare = knife.compare_payload(case, case)
    assert compare["diff_count"] == 1
    assert compare["diffs"][0]["value_diffs"][0]["key"] == "application"
    assert compare["diffs"][0]["value_diffs_flat"][0].startswith("application:")


def test_knife_compare_filters_files_and_raw_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        knife_service,
        "compare_case_dicts",
        lambda _l, _r: [
            DictDiff(
                rel_path="system/controlDict",
                missing_in_left=[],
                missing_in_right=[],
                value_diffs=[ValueDiff(key="application", left="a", right="b")],
                kind="dict",
            ),
            DictDiff(
                rel_path="maxCoSchedule.dat",
                missing_in_left=[],
                missing_in_right=[],
                value_diffs=[],
                kind="file",
                left_hash="1",
                right_hash="2",
            ),
        ],
    )
    payload = knife.compare_payload(
        case,
        case,
        files=["maxCoSchedule.dat"],
        flat=True,
        raw_hash_only=True,
    )
    assert payload["diff_count"] == 1
    assert payload["diffs"][0]["rel_path"] == "maxCoSchedule.dat"
    assert payload["flat"] is True
    assert payload["raw_hash_only"] is True


def test_knife_fallback_solver_and_set_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    control = case / "system" / "controlDict"
    control.write_text("// comment\napplication rhoSimpleFoam;\n")
    assert knife._fallback_solver(control) == "rhoSimpleFoam"

    control.write_text("// no application\n")
    assert knife._fallback_solver(control) is None
    assert knife._fallback_solver(case / "system" / "missing") is None

    monkeypatch.setattr(knife_service, "write_entry", lambda *_a, **_k: False)
    payload = knife.set_entry_payload(case, "system/controlDict", "application", "simpleFoam")
    assert payload["ok"] is False


def test_knife_proc_parsing_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    proc = _write_proc_entry(
        proc_root,
        pid=1,
        ppid=0,
        cmdline=b"/bin/simpleFoam\x00-case\x00.\x00",
        cwd=case,
    )

    assert knife._read_proc_args(proc) == ["/bin/simpleFoam", "-case", "."]
    assert knife._read_proc_args(proc_root / "999") == []
    (proc / "cmdline").write_bytes(b"")
    assert knife._read_proc_args(proc) == []

    assert knife._read_proc_ppid(proc_root / "999") == -1
    bad_stat = _write_proc_entry(proc_root, pid=2, ppid=1, stat_tail="broken")
    assert knife._read_proc_ppid(bad_stat) == -1
    (bad_stat / "stat").write_text("2 (cmd) S x x\n")
    assert knife._read_proc_ppid(bad_stat) == -1

    assert knife._proc_cwd(proc_root / "999") == (proc_root / "999" / "cwd")
    monkeypatch.setattr(Path, "resolve", lambda _self: (_ for _ in ()).throw(OSError("x")))
    assert knife._proc_cwd(proc_root / "999") is None
    assert knife._process_role([], "simplefoam") is None
    assert knife._process_role(["bash"], "simplefoam") is None
    assert knife._process_role(["bash", "-lc", "hy2Foam -parallel"], "hy2foam") == "launcher"
    assert knife._process_role(["mpirun"], "simplefoam") == "launcher"
    assert knife._token_matches_solver("a && /opt/simpleFoam;", "simplefoam") is True


def test_knife_proc_graph_helpers(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case", solver="hy2Foam")
    other = _make_case(tmp_path / "other", solver="hy2Foam")
    table = {
        10: knife.ProcEntry(pid=10, ppid=1, args=["mpirun", "-case", "."], cwd=case),
        11: knife.ProcEntry(pid=11, ppid=10, args=["hy2Foam", "-parallel"], cwd=case),
        12: knife.ProcEntry(pid=12, ppid=10, args=["bash"], cwd=case),
        20: knife.ProcEntry(pid=20, ppid=1, args=["mpirun", "-case", "."], cwd=other),
    }
    launchers = knife._launcher_pids_for_case(table, "hy2foam", case)
    assert 10 in launchers
    assert 20 not in launchers
    assert knife._launcher_has_solver_descendant(10, table, "hy2foam") is True
    assert knife._launcher_has_solver_descendant(20, table, "hy2foam") is False

    assert knife._has_ancestor(11, {10}, table) is True
    assert knife._has_ancestor(50, {10}, table) is False
    cyc = {1: knife.ProcEntry(pid=1, ppid=2, args=["x"], cwd=case), 2: knife.ProcEntry(pid=2, ppid=1, args=["x"], cwd=case)}
    assert knife._has_ancestor(1, {9}, cyc) is False

    assert knife._entry_targets_case(table[10], case) is True
    rel_case = knife.ProcEntry(pid=30, ppid=1, args=["hy2Foam", "-case", "."], cwd=case)
    assert knife._entry_targets_case(rel_case, case) is True
    wrong = knife.ProcEntry(pid=31, ppid=1, args=["hy2Foam", "-case", "."], cwd=other)
    assert knife._entry_targets_case(wrong, case) is False
    missing_arg = knife.ProcEntry(pid=32, ppid=1, args=["hy2Foam", "-case"], cwd=other)
    assert knife._entry_targets_case(missing_arg, case) is False


def test_knife_scan_proc_solver_processes_filters_entries(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case", solver="hy2Foam")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc_entry(proc_root, pid=100, ppid=1, cmdline=b"", cwd=case)
    _write_proc_entry(proc_root, pid=101, ppid=1, cmdline=b"bash\x00", cwd=case)
    _write_proc_entry(
        proc_root,
        pid=102,
        ppid=1,
        cmdline=b"mpirun\x00-case\x00.\x00hy2Foam\x00",
        cwd=case,
    )
    _write_proc_entry(
        proc_root,
        pid=103,
        ppid=102,
        cmdline=b"hy2Foam\x00-parallel\x00-case\x00.\x00",
        cwd=case,
    )

    rows = knife._scan_proc_solver_processes(
        case,
        "hy2Foam",
        tracked_pids={103},
        proc_root=proc_root,
        include_tracked=False,
    )
    pids = [int(row["pid"]) for row in rows]
    assert 102 in pids
    assert 103 not in pids


def test_knife_scan_proc_solver_processes_relaxed_scope(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case", solver="hy2Foam")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc_entry(
        proc_root,
        pid=201,
        ppid=1,
        cmdline=b"mpirun\x00-np\x006\x00hy2Foam\x00-parallel\x00",
        cwd=None,
    )
    _write_proc_entry(
        proc_root,
        pid=202,
        ppid=201,
        cmdline=b"hy2Foam\x00-parallel\x00",
        cwd=None,
    )
    rows = knife._scan_proc_solver_processes(
        case,
        None,
        tracked_pids=set(),
        proc_root=proc_root,
        require_case_target=False,
    )
    assert {int(row["pid"]) for row in rows} == {201, 202}


def test_knife_current_payload_uses_live_scan_to_relax_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "repo", solver="hy2Foam")
    (case / "system" / "controlDict").unlink()
    monkeypatch.setattr(knife_service, "resolve_solver_name", lambda _case: (None, "no controlDict"))
    monkeypatch.setattr(knife_service, "refresh_jobs", lambda _case: [])
    seen: list[bool] = []

    def _scan(
        _case: Path,
        _solver: str | None,
        *,
        tracked_pids: set[int],
        require_case_target: bool = True,
        **_kwargs: object,
    ) -> list[dict[str, object]]:
        del tracked_pids
        seen.append(require_case_target)
        if require_case_target:
            return []
        return [{"pid": 404, "solver": "hy2Foam", "role": "solver", "tracked": False, "command": "hy2Foam -parallel"}]

    monkeypatch.setattr(knife_service, "_scan_proc_solver_processes", _scan)
    payload = knife.current_payload(case)
    assert seen == [True]
    assert payload["jobs_running"] == 0
    payload_live = knife.current_payload(case, live=True)
    assert seen == [True, False]
    assert payload_live["jobs_running"] == 1
    assert payload_live["untracked_processes"][0]["pid"] == 404


def test_knife_current_live_and_report_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    seen: dict[str, object] = {}

    def _status(_case: Path, **kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {
            "case": str(case),
            "solver": "simpleFoam",
            "solver_error": None,
            "running": True,
            "log_path": str(case / "log.simpleFoam"),
            "log_fresh": True,
            "latest_time": 2.0,
            "latest_iteration": 20,
            "latest_delta_t": 1e-9,
            "sec_per_iter": 0.2,
            "eta_seconds_to_criteria_start": 0.0,
            "eta_seconds_to_end_time": 42.0,
            "run_time_control": {
                "criteria_start": 0.0,
                "end_time": 10.0,
                "passed": 0,
                "failed": 1,
                "unknown": 0,
                "criteria": [
                    {
                        "key": "residualTolerance",
                        "status": "fail",
                        "live_value": 0.1,
                        "live_delta": 0.05,
                        "value": "0.01",
                        "tolerance": 0.01,
                        "eta_seconds": 12.0,
                        "samples": 8,
                        "unmet_reason": "window",
                    },
                ],
            },
        }

    monkeypatch.setattr(knife_service, "status_payload", _status)
    criteria = knife.criteria_payload(case, lightweight=True, tail_bytes=2048)
    assert criteria["criteria_count"] == 1
    assert criteria["criteria"][0]["unmet"] == "window"
    assert seen["lightweight"] is True
    assert seen["tail_bytes"] == 2048

    eta = knife.eta_payload(case, mode="criteria", lightweight=True, tail_bytes=2048)
    assert eta["eta_seconds"] == 12.0
    assert eta["eta_end_time_seconds"] == 42.0

    report = knife.report_payload(case, lightweight=True, tail_bytes=2048)
    assert report["criteria"]["failed"] == 1
    assert report["eta"]["criteria_seconds"] == 12.0

    md = knife.report_markdown(report)
    assert "## Criteria" in md
    assert "criteria_seconds: 12.0" in md


def test_knife_current_scope_payload_tree_aggregates_jobs_and_untracked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    case_a = _make_case(root / "a", solver="hy2Foam")
    case_b = _make_case(root / "b", solver="hy2Foam")
    outside = _make_case(tmp_path / "outside", solver="hy2Foam")

    def _refresh(case_path: Path) -> list[dict[str, object]]:
        if case_path == case_a.resolve():
            return [{"id": "a-1", "pid": 111, "status": "running", "name": "hy2Foam"}]
        if case_path == case_b.resolve():
            return [{"id": "b-1", "pid": 222, "status": "finished", "name": "hy2Foam"}]
        return []

    monkeypatch.setattr(knife_service, "refresh_jobs", _refresh)
    monkeypatch.setattr(
        knife_service,
        "_scan_proc_solver_processes",
        lambda _case, _solver, **_k: [
            {
                "pid": 333,
                "solver": "hy2Foam",
                "role": "solver",
                "tracked": False,
                "case": str(case_b.resolve()),
                "command": "hy2Foam -parallel",
            },
            {
                "pid": 444,
                "solver": "hy2Foam",
                "role": "solver",
                "tracked": False,
                "case": str(outside.resolve()),
                "command": "hy2Foam -parallel",
            },
        ],
    )

    payload = knife.current_scope_payload(root, live=True, recursive=True)
    assert payload["scope"] == "tree"
    assert payload["cases_total"] == 2
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["pid"] == 111
    assert payload["jobs"][0]["case"] == str(case_a.resolve())
    assert payload["jobs_running"] == 2
    assert payload["untracked_processes"][0]["pid"] == 333
    assert all(int(row["pid"]) != 444 for row in payload["untracked_processes"])


def test_knife_adopt_payload_registers_untracked_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case", solver="hy2Foam")
    case_str = str(case.resolve())
    monkeypatch.setattr(
        knife_service,
        "current_payload",
        lambda _case, **_kwargs: {
            "case": case_str,
            "solver": "hy2Foam",
            "solver_error": None,
            "jobs": [],
            "jobs_total": 0,
            "jobs_running": 1,
            "jobs_tracked_running": 1,
            "jobs_registry_running": 0,
            "untracked_processes": [
                {
                    "pid": 900,
                    "ppid": 1,
                    "solver": "hy2Foam",
                    "role": "launcher",
                    "tracked": False,
                    "case": case_str,
                    "command": "bash -lc hy2Foam -parallel",
                },
                {
                    "pid": 901,
                    "ppid": 900,
                    "solver": "hy2Foam",
                    "role": "solver",
                    "tracked": False,
                    "launcher_pid": 900,
                    "case": case_str,
                    "command": "hy2Foam -parallel",
                },
            ],
        },
    )
    monkeypatch.setattr(knife_service, "refresh_jobs", lambda _case: [])
    captured: list[tuple[str, int]] = []
    monkeypatch.setattr(
        knife_service,
        "register_job",
        lambda _case, name, pid, *_a, **_k: captured.append((name, pid)) or f"job-{pid}",
    )

    payload = knife.adopt_payload(case)

    assert payload["selected"] == 1
    assert payload["failed"] == []
    assert payload["adopted"][0]["pid"] == 900
    assert captured == [("hy2Foam-launcher", 900)]


def test_knife_adopt_payload_bulk_adopts_child_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    case_a = _make_case(root / "caseA", solver="hy2Foam")
    case_b = _make_case(root / "nested" / "caseB", solver="hy2Foam")
    case_a_str = str(case_a.resolve())
    case_b_str = str(case_b.resolve())

    monkeypatch.setattr(
        knife_service,
        "current_scope_payload",
        lambda _case, **_kwargs: {
            "case": str(root.resolve()),
            "solver": None,
            "solver_error": "no controlDict",
            "jobs": [],
            "jobs_total": 0,
            "jobs_running": 2,
            "jobs_tracked_running": 0,
            "jobs_registry_running": 0,
            "untracked_processes": [
                {
                    "pid": 700,
                    "ppid": 1,
                    "solver": "hy2Foam",
                    "role": "launcher",
                    "tracked": False,
                    "case": case_a_str,
                    "command": "bash -lc hy2Foam -parallel",
                },
                {
                    "pid": 701,
                    "ppid": 700,
                    "solver": "hy2Foam",
                    "role": "solver",
                    "tracked": False,
                    "launcher_pid": 700,
                    "case": case_a_str,
                    "command": "hy2Foam -parallel",
                },
                {
                    "pid": 800,
                    "ppid": 1,
                    "solver": "hy2Foam",
                    "role": "launcher",
                    "tracked": False,
                    "case": case_b_str,
                    "command": "bash -lc hy2Foam -parallel",
                },
            ],
        },
    )
    monkeypatch.setattr(knife_service, "refresh_jobs", lambda _case: [])
    adopted_calls: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        knife_service,
        "register_job",
        lambda case_path, _name, pid, *_a, **_k: adopted_calls.append((case_path, pid)) or f"job-{pid}",
    )

    payload = knife.adopt_payload(root)

    assert payload["scope"] == "tree"
    assert payload["selected"] == 2
    assert payload["failed"] == []
    assert {row["case"] for row in payload["adopted"]} == {case_a_str, case_b_str}
    assert {pid for _case, pid in adopted_calls} == {700, 800}


def test_knife_report_payload_uses_single_status_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    calls = 0

    def _status(_case: Path, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "case": str(case),
            "solver": "simpleFoam",
            "solver_error": None,
            "running": True,
            "log_path": str(case / "log.simpleFoam"),
            "log_fresh": True,
            "latest_time": 2.0,
            "latest_iteration": 20,
            "latest_delta_t": 1e-9,
            "sec_per_iter": 0.2,
            "eta_seconds_to_criteria_start": 0.0,
            "eta_seconds_to_end_time": 42.0,
            "run_time_control": {
                "criteria_start": 0.0,
                "end_time": 10.0,
                "passed": 0,
                "failed": 1,
                "unknown": 0,
                "criteria": [],
            },
        }

    monkeypatch.setattr(knife_service, "status_payload", _status)
    report = knife.report_payload(case, lightweight=False, tail_bytes=None)

    assert calls == 1
    assert report["case"] == str(case)


def test_knife_runtime_and_numeric_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    log = case / "log.simpleFoam"
    log.write_text(
        "\n".join(
            [
                "Time = 1",
                "ExecutionTime = 1 s",
                "deltaT = 0.1",
                "iter = 3",
                "criterionTolerance satisfied",
            ],
        ),
    )
    control = case / "system" / "controlDict"
    control.write_text("startTime 0;\nendTime 5;\ncriterionTolerance 1e-6;\n")
    snap = knife._runtime_control_snapshot(case, "simpleFoam")
    assert snap["latest_time"] == 1.0
    assert snap["latest_delta_t"] == 0.1
    assert snap["latest_iteration"] == 3
    assert snap["run_time_control"]["passed"] == 1

    monkeypatch.setattr(
        knife_service.case_source_service,
        "resolve_log_source",
        lambda _path: (_ for _ in ()).throw(ValueError("none")),
    )
    assert knife._resolve_solver_log(case, "missing") is None

    assert knife._run_time_control_data(tmp_path / "missing-case", "")["criteria"] == []
    assert knife._criterion_status("abc", "abc not satisfied")[0] == "fail"
    assert knife._criterion_status("abc", "abc passed")[0] == "pass"
    assert knife._criterion_status("abc", "abc maybe")[0] == "unknown"
    assert knife._criterion_status("abc", "zzz")[0] == "unknown"

    assert knife._eta_seconds(None, 1.0, [0.0], [0.0]) is None
    assert knife._eta_seconds(2.0, 1.0, [0.0, 1.0], [0.0, 1.0]) == 0.0
    assert knife._eta_seconds(1.0, 2.0, [1.0], [1.0]) is None
    assert knife._eta_seconds(1.0, 2.0, [0.0, 0.0], [0.0, 1.0]) is None
    assert knife._eta_seconds(1.0, 2.0, [0.0, 1.0], [0.0, 0.0]) is None

    assert knife._is_log_fresh(None) is False
    assert knife._latest_iteration("", 3) == 3
    assert knife._latest_iteration("", 0) is None
    assert knife._first_match("", knife._END_TIME_RE) is None
    assert knife._last_float("", knife._DELTA_T_RE) is None
    assert knife._to_float(None) is None
    assert knife._to_float("bad") is None
    assert knife._band([]) is None
    assert knife._thermo_out_of_range_count(["temperature out of range", "foo"]) == 1

    residuals = {"U": [0.0, 0.0, 0.0, 0.0], "p": [1.0, 1.0, 1.0, 1.0], "k": [1.0, 0.5, 0.2, 0.1]}
    flat = knife._residual_flatline(residuals)
    assert "U" not in flat
    assert "p" in flat


def test_knife_run_time_control_extracts_quoted_blocks_and_case_include(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    include_file = case / "system" / "criteria.inc"
    include_file.write_text("residualTolerance 0.02;\n")
    control = case / "system" / "controlDict"
    control.write_text(
        "\n".join(
            [
                'startTime 0;',
                'endTime 100;',
                '#include "$FOAM_CASE/system/criteria.inc"',
                "functions",
                "{",
                '    "auto-stop"',
                "    {",
                "        type runTimeControl;",
                "        timeStart 1.5;",
                "        conditions",
                "        {",
                '            "shock-flat"',
                "            {",
                "                type average;",
                '                fields ("average(p)");',
                "                tolerance 250;",
                "            }",
                "        }",
                "    }",
                "}",
            ],
        ),
    )
    data = knife._run_time_control_data(case, "residualTolerance passed\nshock-flat satisfied\n")
    keys = {str(row["key"]) for row in data["criteria"]}
    assert "residualTolerance" in keys
    assert any(key.startswith("functions.auto-stop.shock-flat.average") for key in keys)
    assert data["criteria_start"] == 1.5
    assert data["passed"] >= 1


def test_knife_status_and_converge_edge_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(knife_service, "resolve_solver_name", lambda _case: (None, "missing solver"))
    monkeypatch.setattr(knife_service, "refresh_jobs", lambda _case: [{"status": "running", "pid": 7}])
    payload = knife.status_payload(case)
    assert payload["solver_error"] == "missing solver"
    assert payload["running"] is False

    log = tmp_path / "log.hy2Foam"
    log.write_text("temperature out of range\n")
    converge = knife.converge_payload(log, strict=False)
    assert converge["ok"] is False


def test_dict_compare_private_helpers(tmp_path: Path) -> None:
    left = _make_case(tmp_path / "left")
    right = _make_case(tmp_path / "right")
    (left / "ofti.tools").write_text("a\n")
    (left / "processor0").mkdir()
    (left / "processor0" / "x").write_text("y\n")
    (left / ".ofti").mkdir()
    (left / ".ofti" / "jobs.json").write_text("{}")
    files = dict_compare._case_file_map(left)
    assert "ofti.tools" in files
    assert all("processor0" not in item for item in files)
    assert all(".ofti" not in item for item in files)

    dat = left / "maxCoSchedule.dat"
    dat.write_text("1\n")
    assert dict_compare._is_dictionary("maxCoSchedule.dat", dat, dat) is False
    assert dict_compare._is_dictionary("system/controlDict", left / "system" / "controlDict", right / "system" / "controlDict")

    (left / "system" / "sampleDict").write_text("FoamFile{}")
    assert dict_compare._is_dictionary(
        "system/sampleDict",
        left / "system" / "sampleDict",
        right / "system" / "controlDict",
    )

    same_left = tmp_path / "same-left.txt"
    same_right = tmp_path / "same-right.txt"
    same_left.write_text("same")
    same_right.write_text("same")
    assert dict_compare._compare_raw_file("x", same_left, same_right) is None

    assert dict_compare._hash_file(tmp_path / "missing.bin") is None
    assert dict_compare._load_dict(tmp_path / "missing.foam")[0] is None


def test_dict_compare_dictionary_error_and_raw_key_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    left = tmp_path / "left.foam"
    right = tmp_path / "right.foam"
    left.write_text("alpha 1;\ntransportModels {\n  precompiledModel on;\n}\n")
    right.write_text("beta 2;\ntransportModels {\n  precompiledModel off;\n}\n")
    monkeypatch.setattr(
        dict_compare,
        "_load_dict",
        lambda path: (None, f"{path.name}: parse failed"),
    )
    diff = dict_compare._compare_dictionary_file("system/controlDict", left, right)
    assert diff is not None
    assert diff.error is not None
    assert "beta" in diff.missing_in_right or "beta" in diff.missing_in_left
    assert any(item.key == "transportModels.precompiledModel" for item in diff.value_diffs)

    keys = dict_compare._raw_key_scan(left)
    assert "alpha" in keys
    assert "transportModels" in keys

    nested = cast(dict[str, object], {"FoamFile": {"skip": 1}, "a": {"b": 1}, "v": [1, 2]})
    flat = dict_compare._flatten_mapping(nested)
    assert flat["a.b"] == "1"
    assert flat["v"] == "(1 2)"
    assert dict_compare._as_str_object_dict({"a": 1}) is not None
    assert dict_compare._as_str_object_dict({1: "bad"}) is None
    assert dict_compare._normalize_scalar("a ; b") == "a b"


def test_knife_stop_payload_includes_untracked_solver_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case", solver="hy2Foam")
    killed: list[int] = []

    monkeypatch.setattr(
        knife_service.watch_service,
        "stop_payload",
        lambda *_a, **_k: {
            "case": str(case),
            "kind": "solver",
            "selected": 0,
            "stopped": [],
            "failed": [],
            "signal": "TERM",
        },
    )
    monkeypatch.setattr(knife_service, "refresh_jobs", lambda _case: [])
    monkeypatch.setattr(
        knife_service.process_scan_service,
        "scan_proc_solver_processes",
        lambda *_a, **_k: [
            {
                "pid": 900,
                "ppid": 1,
                "solver": "hy2Foam",
                "role": "launcher",
                "tracked": False,
                "case": str(case.resolve()),
                "command": "mpirun -np 6 hy2Foam -parallel",
                "launcher_pid": 900,
                "solver_pids": [901],
                "discovery_source": "launcher",
                "discovery_error": "",
            },
            {
                "pid": 901,
                "ppid": 900,
                "solver": "hy2Foam",
                "role": "solver",
                "tracked": False,
                "case": str(case.resolve()),
                "command": "hy2Foam -parallel",
                "launcher_pid": None,
                "discovery_source": "launcher",
                "discovery_error": "",
            },
        ],
    )
    monkeypatch.setattr(knife_service.os, "kill", lambda pid, _sig: killed.append(pid))
    payload = knife.stop_payload(case)
    assert payload["selected"] == 2
    assert payload["untracked"]["selected"] == 2
    assert sorted(killed) == [900, 901]
    assert payload["untracked"]["launcher_pids"] == [900]


def test_knife_campaign_rank_and_compare_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "campaign"
    case_a = _make_case(root / "case_10M")
    _make_case(root / "case_10M_alt")
    _make_case(root / "case_20M")

    def _status(case_dir: Path, **_kwargs: object) -> dict[str, object]:
        base = case_dir.name
        if base == "case_10M":
            criteria = [{"status": "pass", "tolerance": 1.0, "live_value": 0.5}]
        elif base == "case_10M_alt":
            criteria = [{"status": "fail", "tolerance": 1.0, "live_value": 1.5}]
        else:
            criteria = [{"status": "fail", "tolerance": 1.0, "live_value": 2.0}]
        return {
            "case": str(case_dir),
            "running": True,
            "latest_time": 1.0,
            "latest_iteration": 10,
            "latest_delta_t": 1e-9,
            "sec_per_iter": 0.2,
            "jobs_running": 1,
            "run_time_control": {
                "criteria": criteria,
                "passed": sum(1 for row in criteria if row["status"] == "pass"),
            },
        }

    monkeypatch.setattr(knife_service, "status_payload", _status)
    monkeypatch.setattr(
        knife_service,
        "compare_payload",
        lambda left, right, **_kwargs: {
            "left_case": str(left),
            "right_case": str(right),
            "diff_count": 3,
            "diffs": [],
        },
    )

    ranked = knife.campaign_rank_payload(root)
    assert ranked["count"] == 3
    assert ranked["ranked"][0]["case"] == str(case_a.resolve())

    compare = knife.campaign_compare_payload(root, group_by="speed")
    assert compare["group_count"] >= 2
    assert any(row["group"] == "10M" for row in compare["comparisons"])


def test_knife_eta_payload_contains_mode_reason_and_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        knife_service,
        "status_payload",
        lambda *_a, **_k: {
            "case": str(case.resolve()),
            "running": True,
            "eta_seconds_to_criteria_start": None,
            "eta_seconds_to_end_time": 50.0,
            "run_time_control": {
                "criteria_start": 0.0,
                "end_time": 1.0,
                "criteria": [
                    {
                        "key": "c1",
                        "status": "fail",
                        "eta_seconds": None,
                        "unmet_reason": "window",
                    },
                ],
            },
        },
    )
    payload = knife.eta_payload(case, mode="criteria")
    assert payload["eta_mode"] == "end_time"
    assert payload["eta_reason"] == "window"
    assert payload["eta_confidence"] <= 0.4


def test_knife_campaign_stop_keep_payload_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "campaign"
    _make_case(root / "caseA")
    _make_case(root / "caseB")
    _make_case(root / "caseC")
    monkeypatch.setattr(
        knife_service,
        "campaign_rank_payload",
        lambda *_a, **_k: {
            "case": str(root),
            "ranked": [
                {"case": str((root / "caseA").resolve())},
                {"case": str((root / "caseB").resolve())},
                {"case": str((root / "caseC").resolve())},
            ],
        },
    )
    calls: list[Path] = []
    monkeypatch.setattr(
        knife_service,
        "stop_payload",
        lambda case_path, **_k: calls.append(Path(case_path)) or {"case": str(case_path), "failed": []},
    )
    with pytest.raises(ValueError, match="worst must be > 0"):
        knife.campaign_stop_worst_payload(root, worst=0)
    with pytest.raises(ValueError, match="best must be > 0"):
        knife.campaign_keep_best_payload(root, best=0)

    dry_run = knife.campaign_stop_worst_payload(root, worst=2, dry_run=True)
    assert dry_run["selected"] == 2
    assert all(row["dry_run"] for row in dry_run["actions"])

    applied = knife.campaign_keep_best_payload(root, best=1, dry_run=False)
    assert applied["stopped"] == 2
    assert len(calls) == 2


def test_knife_campaign_summary_paths_and_group_helpers(tmp_path: Path) -> None:
    root = tmp_path / "campaign"
    case_a = _make_case(root / "caseA")
    case_b = _make_case(root / "caseB")
    summary = root / "summary.csv"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        "case,speed\n"
        f"{case_a.name},15M\n"
        f"{case_b.resolve()},20M\n"
        "missing,30M\n",
    )
    paths = knife.campaign_case_paths(root, summary_csv=summary)
    assert paths == [case_a.resolve(), case_b.resolve()]

    rows = knife_service._summary_rows(summary)
    assert knife_service._summary_row_for_case(case_a, rows) is not None
    assert knife_service._campaign_group_value(case_a, group_by="speed", summary_rows=rows) == "15M"
    assert knife_service._campaign_group_value(case_a, group_by="other", summary_rows=rows) == "all"


def test_knife_eta_helpers_cover_modes() -> None:
    details = knife_service.criteria_eta_details([], eta_to_criteria_start=None, eta_to_end_time=None)
    assert details["reason"] == "criteria_already_met"

    details = knife_service.criteria_eta_details(
        [{"status": "fail", "key": "c1", "eta_seconds": 4.0, "unmet_reason": ""}],
        eta_to_criteria_start=None,
        eta_to_end_time=20.0,
    )
    assert details["eta_worst_seconds"] == 4.0
    assert knife_service.select_eta(
        requested_mode="criteria",
        criteria_details=details,
        eta_to_end_time=20.0,
    )["mode"] == "criteria"

    details_start = knife_service.criteria_eta_details(
        [{"status": "fail", "key": "c2", "eta_seconds": None, "unmet_reason": "startup"}],
        eta_to_criteria_start=12.0,
        eta_to_end_time=40.0,
    )
    assert details_start["reason"] == "criteria_start_window"
    assert knife_service.select_eta(
        requested_mode="criteria",
        criteria_details=details_start,
        eta_to_end_time=40.0,
    )["mode"] == "criteria_start"

    unavailable = knife_service.select_eta(
        requested_mode="endtime",
        criteria_details={},
        eta_to_end_time=None,
    )
    assert unavailable["mode"] == "unavailable"


def test_knife_stop_untracked_non_case_and_error_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_case = tmp_path / "not-case"
    non_case.mkdir()
    payload = knife_service._stop_untracked_solver_processes(non_case, signal_name="TERM")
    assert payload["reason"] == "case_dir_is_not_openfoam_case"

    case = _make_case(tmp_path / "case", solver="hy2Foam")
    monkeypatch.setattr(knife_service, "refresh_jobs", lambda _case: [])
    monkeypatch.setattr(
        knife_service.process_scan_service,
        "scan_proc_solver_processes",
        lambda *_a, **_k: [
            {
                "pid": 1001,
                "role": "solver",
                "case": str(case.resolve()),
                "launcher_pid": None,
                "command": "hy2Foam -parallel",
            },
        ],
    )
    monkeypatch.setattr(
        knife_service.os,
        "kill",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("denied")),
    )
    failed = knife_service._stop_untracked_solver_processes(case, signal_name="TERM")
    assert failed["selected"] == 1
    assert failed["failed"][0]["error"] == "denied"
