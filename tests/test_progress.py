import os
from pathlib import Path

from ofti.core.progress import progress_evidence


def test_progress_reports_stale_log_and_no_progress(tmp_path: Path) -> None:
    case = tmp_path / "case"
    time_dir = case / "1"
    time_dir.mkdir(parents=True)
    field = time_dir / "U"
    field.write_text("field\n", encoding="utf-8")
    log = case / "log.solver"
    log.write_text("Time = 1\n", encoding="utf-8")
    os.utime(field, (100.0, 100.0))
    os.utime(time_dir, (100.0, 100.0))
    os.utime(log, (100.0, 100.0))

    payload = progress_evidence(
        case,
        process_live=True,
        log_path=log,
        now=500.0,
        stale_after=120.0,
    )

    assert payload["log_age_seconds"] == 400.0
    assert payload["latest_time_write_age_seconds"] == 400.0
    assert payload["reason_codes"] == ["STALE_LOG", "NO_PROGRESS"]


def test_progress_distinguishes_idle_and_paused(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()

    assert progress_evidence(case, process_live=False, now=10.0)["reason_codes"] == ["IDLE"]
    assert progress_evidence(
        case,
        process_live=False,
        paused=True,
        now=10.0,
    )["reason_codes"] == ["PAUSED"]
