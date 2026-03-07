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


def test_knife_current_payload_falls_back_to_relaxed_proc_scan(
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
    assert seen == [True, False]
    assert payload["jobs_running"] == 1
    assert payload["untracked_processes"][0]["pid"] == 404


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
