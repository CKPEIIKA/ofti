from __future__ import annotations

import json
from pathlib import Path

import pytest

from ofti.tools import runtime_control_service as rtc
from ofti.tools import watch_service


def test_runtime_control_include_resolution_and_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    control = case / "system" / "controlDict"
    (case / "system" / "local.inc").write_text("residualTolerance 0.05;\n")
    etc_dir = tmp_path / "etc"
    etc_dir.mkdir()
    (etc_dir / "global.inc").write_text("globalTolerance 1e-3;\n")
    monkeypatch.setenv("FOAM_ETC", str(etc_dir))

    control.write_text(
        "\n".join(
            [
                '#include "local.inc"',
                '#include "missing.inc"',
                '#includeEtc "global.inc"',
                '#includeEtc "missing_etc.inc"',
            ],
        ),
    )

    text = rtc.read_with_local_includes(control, case_root=case)
    assert "residualTolerance 0.05;" in text
    assert "globalTolerance 1e-3;" in text
    assert '#include "missing.inc"' in text

    include_parent = case / "system"
    resolved = rtc.resolve_include_path("includeEtc", "absent.inc", include_parent, case)
    assert resolved == (etc_dir / "absent.inc").resolve()

    assert rtc.strip_include_token('"file.inc"') == "file.inc"
    assert rtc.strip_include_token("<etc/caseDicts>") == "etc/caseDicts"
    assert rtc.parse_block_name('"quoted" {', 0) == ("quoted", 8)
    assert rtc.parse_block_name("1abc", 0) == ("1abc", 4)
    assert rtc.parse_block_name("?", 0) is None
    assert rtc.matching_brace("{ x }", 0) == 4
    assert rtc.matching_brace("{ x ", 0) == -1
    assert rtc.first_block_body("a { x; }", "missing") is None


def test_runtime_control_eta_and_reason_helpers() -> None:
    assert rtc.reason_from_evidence("start window") == "startup"
    assert rtc.reason_from_evidence("not enough samples") == "not_enough_samples"
    assert rtc.reason_from_evidence("window too wide") == "window"
    assert rtc.reason_from_evidence("other") is None

    assert rtc.criterion_unmet_reason(
        status="pass",
        evidence=None,
        criteria_start=None,
        latest_time=None,
        samples=0,
    ) is None
    assert rtc.criterion_unmet_reason(
        status="fail",
        evidence=None,
        criteria_start=2.0,
        latest_time=1.0,
        samples=10,
    ) == "startup"
    assert rtc.criterion_unmet_reason(
        status="unknown",
        evidence=None,
        criteria_start=None,
        latest_time=None,
        samples=1,
    ) == "not_enough_samples"
    assert rtc.criterion_unmet_reason(
        status="unknown",
        evidence=None,
        criteria_start=None,
        latest_time=None,
        samples=8,
    ) == "window"

    assert rtc.criterion_eta_seconds([], tolerance=None, comparator="le", execution_times=[], use_delta=False, status="fail") is None
    assert rtc.criterion_eta_seconds([1, 2], tolerance=0.1, comparator="le", execution_times=[1, 2], use_delta=False, status="fail") is None
    assert rtc.criterion_eta_seconds([1, 2, 3], tolerance=0.1, comparator="le", execution_times=[1], use_delta=False, status="fail") is None
    assert rtc.criterion_eta_seconds([3.0, 2.0, 1.0, 0.5], tolerance=0.1, comparator="le", execution_times=[1, 2, 3, 4], use_delta=False, status="pass") == 0.0

    assert rtc.criterion_eta_samples_needed(1.0, tolerance=1.0, comparator="le", slope=-1.0) == 0.0
    assert rtc.criterion_eta_samples_needed(2.0, tolerance=1.0, comparator="le", slope=0.1) < 0
    assert rtc.criterion_eta_samples_needed(0.5, tolerance=1.0, comparator="ge", slope=-0.1) < 0
    assert rtc.criterion_eta_samples_needed(0.2, tolerance=1.0, comparator="ge", slope=0.2) > 0

    assert rtc.latest_iteration("", 0) is None
    assert rtc.latest_iteration("", 3) == 3
    assert rtc.latest_iteration("iter = 9", 0) == 9
    assert rtc.latest_iteration("Time = 0.1\niter = 9", 1) == 1
    assert rtc.eta_seconds(None, 1.0, [0.1, 0.2], [1.0, 2.0]) is None
    assert rtc.eta_seconds(1.0, 0.5, [0.1, 0.2], [1.0, 2.0]) == 0.0
    assert rtc.eta_seconds(0.1, 0.5, [0.1], [1.0]) is None
    assert rtc.eta_seconds(0.1, 0.5, [0.2, 0.2], [1.0, 2.0]) is None
    assert rtc.eta_seconds(0.1, 0.5, [0.2, 0.3], [1.0, 1.0]) is None
    assert rtc.eta_seconds(0.1, 0.5, [0.1, 0.2], [1.0, 2.0]) is not None


def test_watch_service_branch_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()

    with pytest.raises(ValueError, match="interval must be > 0"):
        watch_service.interval_payload(case, seconds=0)

    with pytest.raises(ValueError, match="watcher command is required"):
        watch_service.watcher_start_payload(case, command=None, dry_run=False)

    (case / "ofti.watcher").write_text("# empty preset\n")
    with pytest.raises(ValueError, match="watcher command not found in preset"):
        watch_service.watcher_start_payload(case, command=None, dry_run=False)

    dry_start = watch_service.watcher_start_payload(case, command=["echo", "x"], dry_run=True)
    assert dry_start["ok"] is True

    dry_run = watch_service.watcher_run_payload(case, command=["echo", "x"], dry_run=True)
    assert dry_run["ok"] is True

    called: list[str] = []
    monkeypatch.setattr(watch_service, "watcher_start_payload", lambda *_a, **_k: called.append("start") or {"ok": True})
    monkeypatch.setattr(watch_service, "watcher_run_payload", lambda *_a, **_k: called.append("run") or {"ok": True})
    watch_service.watcher_attach_payload(case, command=["echo"], background=True)
    watch_service.watcher_attach_payload(case, command=["echo"], background=False)
    assert called == ["start", "run"]

    log_path = case / "log.bad"
    log_path.write_text("x\n")
    monkeypatch.setattr(watch_service, "read_log_tail_lines", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(ValueError, match="failed to read"):
        watch_service._tail_payload_from_log(log_path, lines=5)

    with pytest.raises(ValueError, match="external watcher command is required"):
        watch_service.external_watch_start_payload(case, command=[], dry_run=False)
    assert watch_service.external_watch_start_payload(case, command=[], dry_run=True)["ok"] is True

    for mode in ("start", "status", "attach", "stop"):
        def _payload(*_a: object, _mode: str = mode, **_k: object) -> dict[str, str]:
            return {"mode": _mode}

        monkeypatch.setattr(watch_service, f"external_watch_{mode}_payload", _payload)
        payload = watch_service.external_watch_mode_payload(case, mode=mode, command=["x"], dry_run=True)
        assert payload["mode"] == mode


def test_watch_service_adopt_and_misc_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "log.simpleFoam").write_text("solver\n")
    (case / "log.other").write_text("other\n")

    with pytest.raises(ValueError, match="adopt target is empty"):
        watch_service._resolve_adopt_pid("", case)
    with pytest.raises(ValueError, match="invalid adopt pid"):
        watch_service._resolve_adopt_pid("0", case)

    monkeypatch.setattr(watch_service.case_source_service, "require_case_dir", lambda _p: case)
    monkeypatch.setattr(watch_service.process_scan_service, "scan_proc_solver_processes", lambda *_a, **_k: [])
    with pytest.raises(ValueError, match="no running solver processes found"):
        watch_service._resolve_adopt_pid("not-a-pid", case)

    monkeypatch.setattr(
        watch_service.process_scan_service,
        "scan_proc_solver_processes",
        lambda *_a, **_k: [{"pid": 0, "role": "solver"}],
    )
    with pytest.raises(ValueError, match="invalid solver pid"):
        watch_service._resolve_adopt_pid("case-token", case)

    monkeypatch.setattr(
        watch_service.process_scan_service,
        "scan_proc_solver_processes",
        lambda *_a, **_k: [{"pid": 111, "role": "solver"}],
    )
    assert watch_service._resolve_adopt_pid("case-token", case) == 111

    assert watch_service._adopt_log_path(case, "simpleFoam").name == "log.simpleFoam"
    assert watch_service._adopt_log_path(case, "missing").name == "log.other"
    empty_case = tmp_path / "empty"
    empty_case.mkdir()
    assert watch_service._adopt_log_path(empty_case, None).name == "log.solver"

    rel = watch_service._external_log_path(case, name="watch.external", raw="logs/watch.log")
    assert rel == (case / "logs/watch.log").resolve()
    assert watch_service._external_jobs(
        [{"name": "watch.custom", "kind": "watcher"}, {"name": "simpleFoam", "kind": "solver"}],
        name="",
    ) == []

    rows = [{"id": "1", "name": "watch.external", "kind": "watcher", "status": "finished"}]
    monkeypatch.setattr(watch_service, "refresh_jobs", lambda _c: rows)
    with pytest.raises(ValueError, match="external watcher job not found"):
        watch_service._select_external_job(case, job_id="2", name="watch.external")
    with pytest.raises(ValueError, match="no tracked external watcher jobs"):
        watch_service._select_external_job(case, job_id=None, name="other")

    assert watch_service._infer_job_kind({"name": "watch-daemon"}) == "watcher"
    assert watch_service._resolve_watcher_command(case, ["--", "python", "w.py"])[0] == ["python", "w.py"]
    assert watch_service._signal_by_name("TERM") == int(watch_service.signal.SIGTERM)

    bad_json = case / ".ofti" / "watch.json"
    bad_json.parent.mkdir(parents=True, exist_ok=True)
    bad_json.write_text(json.dumps(["bad"]))
    assert watch_service._load_watch_settings(case) == {}

    monkeypatch.setenv("MIND_URL", "https://mind")
    env = watch_service._watcher_env(case, watcher_id="w-1", preset_env={}, extra_env=None)
    assert env["MIND_URL"] == "https://mind"

    jobs = [{"id": "1", "status": "running"}]
    selected = watch_service._select_jobs(jobs, statuses={"running"}, job_id=None, name=None, all_jobs=False)
    assert selected == jobs

    orig_resolve = Path.resolve

    def _resolve_fail(self: Path, strict: bool = False) -> Path:
        if self.name == "bad.log":
            raise OSError("boom")
        return orig_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_fail)
    assert watch_service._job_log_path(case, {"log": "bad.log"}) == str(case / "bad.log")

    monkeypatch.setattr(watch_service, "refresh_jobs", lambda _c: [{"id": "x", "name": "watch.external", "kind": "watcher", "status": "running"}])
    status = watch_service.external_watch_status_payload(case, job_id="x", name="watch.external", include_all=True)
    assert status["count"] == 1

    monkeypatch.setattr(watch_service, "refresh_jobs", lambda _c: [{"id": "1", "pid": "bad", "status": "running"}])
    monkeypatch.setattr(watch_service.process_scan_service, "proc_table", lambda _root: {})
    with pytest.raises(ValueError, match="process not found"):
        watch_service.adopt_job_payload(case, adopt="123")


def test_watch_service_remaining_helper_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(ValueError, match="watcher command is required"):
        watch_service.watcher_run_payload(case, command=None, dry_run=False)

    (case / "ofti.watcher").write_text('bad: "unterminated\nenv KEY=1\n')
    with pytest.raises(ValueError, match="watcher command not found in preset"):
        watch_service.watcher_run_payload(case, command=None, dry_run=False)

    assert watch_service._watcher_command_text("command") == "command"
    assert watch_service._watcher_command_text("x:") == "x:"
    assert watch_service._watcher_command_text("field: value") == "value"
    assert watch_service._watcher_command_text("command: run.sh") == "run.sh"
    assert watch_service._env_assignment_from_line("env KEY=1") == ("KEY", "1")
    assert watch_service._env_assignment_from_line("=x") is None
    assert watch_service._env_assignment_from_line("BAD-NAME=1") is None

    calls: list[Path] = []

    def _require(path: Path) -> Path:
        calls.append(path)
        return other if len(calls) == 1 else case

    monkeypatch.setattr(watch_service.case_source_service, "require_case_dir", _require)
    monkeypatch.setattr(
        watch_service.process_scan_service,
        "scan_proc_solver_processes",
        lambda target_case, *_a, **_k: [] if target_case == other else [{"pid": 333, "role": "solver"}],
    )
    assert watch_service._resolve_adopt_pid("token", case, source_case=other) == 333

    monkeypatch.setattr(
        watch_service,
        "refresh_jobs",
        lambda _c: [{"id": "a", "name": "watch.external", "kind": "watcher", "status": "running"}],
    )
    assert watch_service._select_external_job(case, job_id="a", name="watch.external")["id"] == "a"

    preset = case / "ofti.watcher"
    orig_read_text = Path.read_text

    def _raise_read(
        self: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if self == preset:
            raise OSError("no read")
        return orig_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", _raise_read)
    assert watch_service._load_watcher_preset(preset) == {"command": [], "env": {}}
