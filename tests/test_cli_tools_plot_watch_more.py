from __future__ import annotations

import json
import types
from pathlib import Path

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
