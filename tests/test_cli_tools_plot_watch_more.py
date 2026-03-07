from __future__ import annotations

import json
import types
from pathlib import Path
from typing import cast

import pytest

from ofti.tools import plot_service, watch_service
from ofti.tools.cli_tools import plot, watch


def test_plot_residuals_payload_filters_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = Path("log.simpleFoam")
    monkeypatch.setattr(plot_service, "case_source_service", types.SimpleNamespace(resolve_log_source=lambda _source: log_path))
    monkeypatch.setattr(plot_service, "read_log_text", lambda _path: "log")
    monkeypatch.setattr(
        plot_service,
        "parse_residuals",
        lambda _text: {"U": [1.0, 0.5], "p": [0.2], "k": []},
    )

    payload = plot.residuals_payload(Path(), fields=["p"], limit=1)
    assert payload["log"] == str(log_path)
    assert payload["fields"] == [{"field": "p", "count": 1, "last": 0.2, "min": 0.2, "max": 0.2}]

    payload_all = plot.residuals_payload(Path(), fields=None, limit=1)
    assert len(payload_all["fields"]) == 1


def test_plot_metrics_payload_without_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = Path("log.hy2Foam")
    monkeypatch.setattr(plot_service, "case_source_service", types.SimpleNamespace(resolve_log_source=lambda _source: log_path))
    monkeypatch.setattr(plot_service, "read_log_text", lambda _path: "log")
    monkeypatch.setattr(
        plot_service,
        "parse_log_metrics_and_residuals",
        lambda _text: (
            types.SimpleNamespace(times=[0.1], courants=[0.3], execution_times=[1.2]),
            {"rho": [1e-3]},
        ),
    )
    monkeypatch.setattr(plot_service, "execution_time_deltas", lambda _values: [])

    payload = plot.metrics_payload(Path())
    assert payload["execution_time"]["delta_avg"] is None
    assert payload["residual_fields"] == ["rho"]


def test_watch_stop_payload_selection_and_external(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(
        watch_service,
        "refresh_jobs",
        lambda _case: [
            {"id": "1", "name": "solverA", "pid": 11, "status": "running"},
            {"id": "2", "name": "solverB", "pid": 22, "status": "running"},
        ],
    )
    stopped: list[tuple[str, str]] = []
    monkeypatch.setattr(watch_service, "finish_job", lambda _c, job_id, status, _rc: stopped.append((job_id, status)))
    monkeypatch.setattr(watch_service.os, "kill", lambda *_a, **_k: None)

    assert watch.stop_payload(case, job_id="2")["selected"] == 1
    assert watch.stop_payload(case, name="solverA")["selected"] == 1
    assert watch.stop_payload(case)["selected"] == 1
    assert ("2", "stopped") in stopped

    dry = watch.external_watch_payload(case, command=[], dry_run=True)
    assert dry["ok"] is True
    with pytest.raises(ValueError, match="external watcher command is required"):
        watch.external_watch_payload(case, command=[], dry_run=False)


def test_watch_external_payload_runs_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()

    class _Popen:
        def __init__(self, _command: list[str], **_kwargs: object) -> None:
            self.pid = 123

        def wait(self) -> int:
            return 1

    monkeypatch.setattr(watch_service.subprocess, "Popen", _Popen)
    payload = watch.external_watch_payload(case, command=["python", "watcher.py"], dry_run=False)
    assert payload["pid"] == 123
    assert payload["returncode"] == 1
    assert payload["ok"] is False


def test_watch_external_mode_and_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    assert watch.external_watch_mode(start=True, status=True) is None
    assert watch.external_watch_mode(start=True) == "start"
    assert watch.normalize_external_command(["--", "python", "w.py"]) == ["python", "w.py"]
    assert watch.normalize_external_command(["python", "w.py"]) == ["python", "w.py"]

    monkeypatch.setattr(
        watch_service,
        "external_watch_payload",
        lambda *_a, **_k: {"case": str(case), "command": ["python"], "dry_run": True, "ok": True},
    )
    payload = watch.external_watch_mode_payload(
        case,
        mode="run",
        command=["python"],
        dry_run=True,
    )
    assert payload["ok"] is True


def test_watch_external_start_status_attach_stop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    ext_log = case / "log.watch.external"
    ext_log.write_text("line1\nline2\nline3\n")
    seen: dict[str, object] = {}

    class _Popen:
        def __init__(self, cmd: list[str], **kwargs: object) -> None:
            self.pid = 777
            seen["cmd"] = cmd
            seen.update(kwargs)

    monkeypatch.setattr(watch_service.subprocess, "Popen", _Popen)
    monkeypatch.setattr(watch_service, "register_job", lambda *_a, **_k: "job-ext-1")
    started = watch.external_watch_start_payload(
        case,
        command=["python", "watcher.py", "--x"],
        dry_run=False,
        name="watch.external",
        detached=True,
        log_file=str(ext_log),
    )
    assert started["pid"] == 777
    assert started["job_id"] == "job-ext-1"
    assert seen["cwd"] == case

    jobs = [
        {
            "id": "job-ext-1",
            "name": "watch.external",
            "pid": 777,
            "status": "running",
            "log": str(ext_log),
            "started_at": 10.0,
        },
        {"id": "x", "name": "solver", "pid": 1, "status": "running"},
    ]
    monkeypatch.setattr(watch_service, "refresh_jobs", lambda _case: jobs)
    monkeypatch.setattr(watch_service, "load_jobs", lambda _case: jobs)
    status = watch.external_watch_status_payload(case, name="watch.external", include_all=False)
    assert status["count"] == 1
    assert status["jobs"][0]["id"] == "job-ext-1"

    attached = watch.external_watch_attach_payload(case, lines=2, name="watch.external")
    assert attached["lines"] == ["line2", "line3"]
    assert attached["job_id"] == "job-ext-1"

    monkeypatch.setattr(watch_service.os, "kill", lambda *_a, **_k: None)
    monkeypatch.setattr(watch_service, "finish_job", lambda *_a, **_k: None)
    stopped = watch.external_watch_stop_payload(case, name="watch.external", all_jobs=True)
    assert stopped["selected"] == 1
    assert stopped["signal"] == "TERM"


def test_watch_interval_output_and_adopt_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()

    interval = watch.interval_payload(case, seconds=0.7)
    assert interval["effective"] == 0.7
    assert watch.effective_interval(case) == 0.7

    output = watch.output_profile_payload(case, profile="brief")
    assert output["effective"] == "brief"
    assert watch.effective_output_profile(case) == "brief"

    monkeypatch.setattr(
        watch_service,
        "refresh_jobs",
        lambda _case: [{"id": "job-1", "pid": 100, "status": "running", "log": "log.simpleFoam"}],
    )
    already = watch.adopt_job_payload(case, adopt="100")
    assert already["adopted"] is False
    assert already["reason"] == "already_tracked"

    monkeypatch.setattr(watch_service, "refresh_jobs", lambda _case: [])
    monkeypatch.setattr(
        watch_service.process_scan_service,
        "proc_table",
        lambda _root: {
            101: watch_service.process_scan_service.ProcEntry(
                pid=101,
                ppid=1,
                args=["simpleFoam", "-case", "."],
                cwd=case,
            ),
        },
    )
    monkeypatch.setattr(watch_service, "register_job", lambda *_a, **_k: "job-new")
    adopted = watch.adopt_job_payload(case, adopt="101")
    assert adopted["adopted"] is True
    assert adopted["job_id"] == "job-new"


def test_watch_log_path_from_job_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(watch_service, "load_jobs", lambda _case: [{"id": "1", "log": ""}])
    with pytest.raises(ValueError, match="has no log path"):
        watch_service._log_path_from_job(case, "1")

    monkeypatch.setattr(watch_service, "load_jobs", lambda _case: [{"id": "1", "log": "log.missing"}])
    with pytest.raises(ValueError, match="not found"):
        watch_service._log_path_from_job(case, "1")


def test_jobs_pause_resume_and_signal_controls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    jobs_file = case / ".ofti" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text(
        json.dumps(
            [
                {"id": "a", "name": "solverA", "pid": 11, "status": "running"},
                {"id": "b", "name": "solverB", "pid": 22, "status": "paused"},
            ],
        ),
    )
    monkeypatch.setattr(watch_service, "refresh_jobs", lambda _case: watch_service.load_jobs(case))
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(watch_service.os, "kill", lambda pid, sig: sent.append((pid, int(sig))))

    jobs = watch.jobs_payload(case, include_all=False)
    assert jobs["count"] == 2

    paused = watch.pause_payload(case, job_id="a")
    assert paused["selected"] == 1
    assert paused["paused"][0]["id"] == "a"
    statuses = {str(job["id"]): str(job["status"]) for job in watch_service.load_jobs(case)}
    assert statuses["a"] == "paused"

    resumed = watch.resume_payload(case, job_id="b")
    assert resumed["selected"] == 1
    assert resumed["resumed"][0]["id"] == "b"
    statuses = {str(job["id"]): str(job["status"]) for job in watch_service.load_jobs(case)}
    assert statuses["b"] == "running"

    stopped = watch.stop_payload(case, all_jobs=True, signal_name="INT")
    assert stopped["signal"] == "INT"
    with pytest.raises(ValueError, match="unsupported signal"):
        watch.stop_payload(case, signal_name="HUP")
    assert sent


def test_watch_pause_resume_invalid_pid_and_kill_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(
        watch_service,
        "refresh_jobs",
        lambda _case: [
            {"id": "bad", "name": "solverA", "pid": "oops", "status": "running"},
            {"id": "missing", "name": "solverB", "pid": 99, "status": "paused"},
        ],
    )
    finished: list[tuple[str, str]] = []
    monkeypatch.setattr(
        watch_service,
        "finish_job",
        lambda _c, job_id, status, _rc: finished.append((str(job_id), str(status))),
    )

    def _kill(pid: int, sig: int) -> None:
        raise OSError(f"no such process: {pid}/{sig}")

    monkeypatch.setattr(watch_service.os, "kill", _kill)
    paused = watch.pause_payload(case, all_jobs=True)
    assert paused["failed"][0]["id"] == "bad"
    resumed = watch.resume_payload(case, all_jobs=True)
    assert resumed["failed"][0]["id"] == "missing"
    assert ("missing", "missing") in finished


def test_watch_signal_name_maps_quit_and_kill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(
        watch_service,
        "refresh_jobs",
        lambda _case: [{"id": "1", "name": "solver", "pid": 42, "status": "running"}],
    )
    monkeypatch.setattr(watch_service, "finish_job", lambda *_args, **_kwargs: None)
    sent: list[int] = []
    monkeypatch.setattr(watch_service.os, "kill", lambda _pid, sig: sent.append(int(sig)))

    watch.stop_payload(case, all_jobs=True, signal_name="QUIT")
    watch.stop_payload(case, all_jobs=True, signal_name="KILL")
    assert sent[-2:] == [int(watch.signal.SIGQUIT), int(watch.signal.SIGKILL)]


def test_watch_jobs_payload_schema_and_kind_filter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "log.simpleFoam").write_text("solver\n")
    (case / "log.watcher").write_text("watcher\n")
    monkeypatch.setattr(
        watch_service,
        "refresh_jobs",
        lambda _case: [
            {"id": "s1", "name": "simpleFoam", "pid": 11, "status": "running", "log": "log.simpleFoam"},
            {
                "id": "w1",
                "name": "watcher",
                "kind": "watcher",
                "pid": 22,
                "status": "paused",
                "log": "log.watcher",
                "detached": True,
            },
        ],
    )

    payload = watch.jobs_payload(case, include_all=True, kind="watcher")
    assert payload["count"] == 1
    row = payload["jobs"][0]
    assert row["kind"] == "watcher"
    assert row["running"] is True
    assert row["detached"] is True
    assert row["case_dir"] == str(case.resolve())
    assert str(row["log_path"]).endswith("log.watcher")

    with pytest.raises(ValueError, match="unsupported job kind"):
        watch.jobs_payload(case, include_all=True, kind="bad")


def test_watch_watcher_preset_start_and_run_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "ofti.watcher").write_text(
        "\n".join(
            [
                "# watcher preset",
                "watcher: python scripts/watcher.py --poll 1",
                "FRAMEWORK=custom",
                "RELAY_BASE_URL=https://relay.example",
            ],
        ),
    )
    dry = watch.watcher_preset_payload(case)
    assert dry["found"] is True
    assert dry["command"][:2] == ["python", "scripts/watcher.py"]

    captured_register: dict[str, object] = {}

    class _StartPopen:
        def __init__(self, _cmd: list[str], **_kwargs: object) -> None:
            self.pid = 333

    monkeypatch.setattr(watch_service.subprocess, "Popen", _StartPopen)

    def _register(*args: object, **kwargs: object) -> str:
        captured_register["args"] = args
        captured_register["kwargs"] = kwargs
        return "watch-job-1"

    monkeypatch.setattr(watch_service, "register_job", _register)
    started = watch.watcher_start_payload(
        case,
        command=[],
        detached=True,
        env={"WATCHER_ID": "w-1"},
        dry_run=False,
        name="watcher",
    )
    assert started["ok"] is True
    assert started["job_id"] == "watch-job-1"
    kwargs = cast(dict[str, object], captured_register["kwargs"])
    assert kwargs["kind"] == "watcher"
    assert kwargs["detached"] is True

    class _RunPopen:
        def __init__(self, _cmd: list[str], **_kwargs: object) -> None:
            self.pid = 444

        def wait(self) -> int:
            return 1

    finished: list[tuple[str | None, str, int | None]] = []
    monkeypatch.setattr(watch_service.subprocess, "Popen", _RunPopen)
    monkeypatch.setattr(
        watch_service,
        "finish_job",
        lambda _c, job_id, status, rc: finished.append((job_id, status, rc)),
    )
    monkeypatch.setattr(watch_service, "register_job", lambda *_a, **_k: "watch-job-2")
    run_payload = watch.watcher_run_payload(case, command=[], dry_run=False, name="watcher")
    assert run_payload["ok"] is False
    assert run_payload["returncode"] == 1
    assert finished == [("watch-job-2", "failed", 1)]


def test_watch_stop_kind_filter_for_watcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(
        watch_service,
        "refresh_jobs",
        lambda _case: [
            {"id": "solver-1", "name": "simpleFoam", "kind": "solver", "pid": 11, "status": "running"},
            {"id": "watch-1", "name": "watcher", "kind": "watcher", "pid": 22, "status": "running"},
        ],
    )
    monkeypatch.setattr(watch_service.os, "kill", lambda *_a, **_k: None)
    monkeypatch.setattr(watch_service, "finish_job", lambda *_a, **_k: None)
    payload = watch.stop_payload(case, all_jobs=True, kind="watcher")
    assert payload["selected"] == 1
    assert payload["stopped"][0]["id"] == "watch-1"
