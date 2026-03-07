from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from ofti.tools.cli_tools import plot, watch


def test_plot_residuals_payload_filters_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = Path("log.simpleFoam")
    monkeypatch.setattr(plot, "resolve_log_source", lambda _source: log_path)
    monkeypatch.setattr(plot, "read_text", lambda _path: "log")
    monkeypatch.setattr(
        plot,
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
    monkeypatch.setattr(plot, "resolve_log_source", lambda _source: log_path)
    monkeypatch.setattr(plot, "read_text", lambda _path: "log")
    monkeypatch.setattr(
        plot,
        "parse_log_metrics",
        lambda _text: types.SimpleNamespace(times=[0.1], courants=[0.3], execution_times=[1.2]),
    )
    monkeypatch.setattr(plot, "parse_residuals", lambda _text: {"rho": [1e-3]})
    monkeypatch.setattr(plot, "execution_time_deltas", lambda _values: [])

    payload = plot.metrics_payload(Path())
    assert payload["execution_time"]["delta_avg"] is None
    assert payload["residual_fields"] == ["rho"]


def test_watch_stop_payload_selection_and_external(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(
        watch,
        "refresh_jobs",
        lambda _case: [
            {"id": "1", "name": "solverA", "pid": 11, "status": "running"},
            {"id": "2", "name": "solverB", "pid": 22, "status": "running"},
        ],
    )
    stopped: list[tuple[str, str]] = []
    monkeypatch.setattr(watch, "finish_job", lambda _c, job_id, status, _rc: stopped.append((job_id, status)))
    monkeypatch.setattr(watch.os, "kill", lambda *_a, **_k: None)

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

    monkeypatch.setattr(watch.subprocess, "Popen", _Popen)
    payload = watch.external_watch_payload(case, command=["python", "watcher.py"], dry_run=False)
    assert payload["pid"] == 123
    assert payload["returncode"] == 1
    assert payload["ok"] is False


def test_watch_log_path_from_job_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(watch, "load_jobs", lambda _case: [{"id": "1", "log": ""}])
    with pytest.raises(ValueError, match="has no log path"):
        watch._log_path_from_job(case, "1")

    monkeypatch.setattr(watch, "load_jobs", lambda _case: [{"id": "1", "log": "log.missing"}])
    with pytest.raises(ValueError, match="not found"):
        watch._log_path_from_job(case, "1")


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
    monkeypatch.setattr(watch, "refresh_jobs", lambda _case: watch.load_jobs(case))
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(watch.os, "kill", lambda pid, sig: sent.append((pid, int(sig))))

    jobs = watch.jobs_payload(case, include_all=False)
    assert jobs["count"] == 2

    paused = watch.pause_payload(case, job_id="a")
    assert paused["selected"] == 1
    assert paused["paused"][0]["id"] == "a"
    statuses = {str(job["id"]): str(job["status"]) for job in watch.load_jobs(case)}
    assert statuses["a"] == "paused"

    resumed = watch.resume_payload(case, job_id="b")
    assert resumed["selected"] == 1
    assert resumed["resumed"][0]["id"] == "b"
    statuses = {str(job["id"]): str(job["status"]) for job in watch.load_jobs(case)}
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
        watch,
        "refresh_jobs",
        lambda _case: [
            {"id": "bad", "name": "solverA", "pid": "oops", "status": "running"},
            {"id": "missing", "name": "solverB", "pid": 99, "status": "paused"},
        ],
    )
    finished: list[tuple[str, str]] = []
    monkeypatch.setattr(
        watch,
        "finish_job",
        lambda _c, job_id, status, _rc: finished.append((str(job_id), str(status))),
    )

    def _kill(pid: int, sig: int) -> None:
        raise OSError(f"no such process: {pid}/{sig}")

    monkeypatch.setattr(watch.os, "kill", _kill)
    paused = watch.pause_payload(case, all_jobs=True)
    assert paused["failed"][0]["id"] == "bad"
    resumed = watch.resume_payload(case, all_jobs=True)
    assert resumed["failed"][0]["id"] == "missing"
    assert ("missing", "missing") in finished


def test_watch_signal_name_maps_quit_and_kill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(
        watch,
        "refresh_jobs",
        lambda _case: [{"id": "1", "name": "solver", "pid": 42, "status": "running"}],
    )
    monkeypatch.setattr(watch, "finish_job", lambda *_args, **_kwargs: None)
    sent: list[int] = []
    monkeypatch.setattr(watch.os, "kill", lambda _pid, sig: sent.append(int(sig)))

    watch.stop_payload(case, all_jobs=True, signal_name="QUIT")
    watch.stop_payload(case, all_jobs=True, signal_name="KILL")
    assert sent[-2:] == [int(watch.signal.SIGQUIT), int(watch.signal.SIGKILL)]
