from __future__ import annotations

from pathlib import Path

from ofti.tools import job_control_service, runtime_control_service, watch_service
from ofti.tools.cli_tools import knife, watch


def test_knife_runtime_snapshot_wrapper_delegates(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _snapshot(
        case_path: Path,
        solver: str | None,
        *,
        resolve_log_source_fn,
    ) -> dict[str, object]:
        seen["case"] = case_path
        seen["solver"] = solver
        seen["resolver"] = resolve_log_source_fn
        return {"ok": True}

    monkeypatch.setattr(runtime_control_service, "runtime_control_snapshot", _snapshot)
    payload = knife._runtime_control_snapshot(Path("case"), "hy2Foam")
    assert payload == {"ok": True}
    assert seen["case"] == Path("case")
    assert seen["solver"] == "hy2Foam"
    assert callable(seen["resolver"])


def test_knife_runtime_snapshot_wrapper_forwards_lightweight(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _snapshot(
        _case_path: Path,
        _solver: str | None,
        *,
        resolve_log_source_fn,
        lightweight: bool,
        max_log_bytes: int | None,
    ) -> dict[str, object]:
        seen["lightweight"] = lightweight
        seen["max_log_bytes"] = max_log_bytes
        seen["resolver"] = resolve_log_source_fn
        return {"ok": True}

    monkeypatch.setattr(runtime_control_service, "runtime_control_snapshot", _snapshot)
    payload = knife._runtime_control_snapshot(Path("case"), "hy2Foam", lightweight=True, max_log_bytes=2048)
    assert payload == {"ok": True}
    assert seen["lightweight"] is True
    assert seen["max_log_bytes"] == 2048


def test_watch_stop_wrapper_delegates(monkeypatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    seen: dict[str, object] = {}
    monkeypatch.setattr(watch_service.case_source_service, "require_case_dir", lambda _path: case)
    monkeypatch.setattr(watch_service, "refresh_jobs", lambda _case: [{"id": "job-1", "status": "running"}])

    def _stop(
        case_path: Path,
        jobs,
        *,
        job_id,
        name,
        all_jobs,
        signal_name,
        kill_fn,
        finish_job_fn,
    ) -> dict[str, object]:
        seen["case"] = case_path
        seen["jobs"] = jobs
        seen["job_id"] = job_id
        seen["name"] = name
        seen["all_jobs"] = all_jobs
        seen["signal_name"] = signal_name
        seen["kill_fn"] = kill_fn
        seen["finish_job_fn"] = finish_job_fn
        return {"signal": signal_name, "selected": 0, "stopped": [], "failed": []}

    monkeypatch.setattr(job_control_service, "stop_jobs", _stop)
    payload = watch.stop_payload(case, signal_name="TERM")
    assert payload["selected"] == 0
    assert seen["case"] == case
    assert seen["signal_name"] == "TERM"
    assert callable(seen["kill_fn"])
    assert callable(seen["finish_job_fn"])
