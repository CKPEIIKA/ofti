from __future__ import annotations

from pathlib import Path

from ofti.tools import job_control, job_control_service, watch_service
from ofti.tools.cli_tools import watch


class _Menu:
    def __init__(self, choice: int) -> None:
        self._choice = choice

    def navigate(self) -> int:
        return self._choice


def test_cli_and_tui_stop_use_same_job_control_service(
    monkeypatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    calls: list[str] = []

    def _stop_jobs(
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
        del jobs, job_id, name, all_jobs, signal_name, kill_fn, finish_job_fn
        calls.append(str(case_path))
        return {"signal": "TERM", "selected": 1, "stopped": [{"id": "1", "pid": 7}], "failed": []}

    monkeypatch.setattr(job_control_service, "stop_jobs", _stop_jobs)

    monkeypatch.setattr(watch_service.case_source_service, "require_case_dir", lambda _path: case)
    monkeypatch.setattr(watch_service, "refresh_jobs", lambda _case: [{"id": "1", "status": "running", "pid": 7}])
    payload = watch.stop_payload(case, all_jobs=True, signal_name="TERM")
    assert payload["selected"] == 1

    monkeypatch.setattr(
        job_control.watch_service,
        "refresh_jobs",
        lambda _case: [{"id": "1", "name": "solver", "pid": 7, "status": "running"}],
    )
    monkeypatch.setattr(job_control, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(job_control, "_show_message", lambda *_a, **_k: None)
    job_control.stop_job_screen(object(), case)

    assert calls == [str(case), str(case)]
