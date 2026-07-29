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

    idle = progress_evidence(case, process_live=False, now=10.0)
    assert idle["reason_codes"] == ["IDLE"]
    assert idle["state"] == "STALLED_LOG"
    paused = progress_evidence(
        case,
        process_live=False,
        paused=True,
        now=10.0,
    )
    assert paused["reason_codes"] == ["PAUSED"]
    assert paused["state"] == "STALLED_LOG"


def test_progress_lifecycle_states_are_explicit(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    log = case / "log.solver"

    assert progress_evidence(case, process_live=True, log_path=log)["state"] == "STARTING"

    log.write_text("Time = 1\nSolving for Ux\n", encoding="utf-8")
    assert progress_evidence(case, process_live=True, log_path=log)["state"] == "SOLVING"

    log.write_text("Time = 1\nWriting fields\n", encoding="utf-8")
    assert progress_evidence(case, process_live=True, log_path=log)["state"] == "WRITING"

    log.write_text("Time = 1\nEnd\n", encoding="utf-8")
    finished = progress_evidence(case, process_live=False, log_path=log)
    assert finished["state"] == "FINISHED"
    assert finished["clean_end_seen"] is True

    log.write_text("MPI_ABORT was invoked on rank 1\n", encoding="utf-8")
    failed = progress_evidence(case, process_live=False, log_path=log)
    assert failed["state"] == "MPI_FAILED"
    assert failed["reason_codes"] == ["IDLE", "MPI_FAILED"]


def test_progress_reports_partial_processor_checkpoint(tmp_path: Path) -> None:
    case = tmp_path / "case"
    for processor in ("processor0", "processor1"):
        field = case / processor / "1" / "U"
        field.parent.mkdir(parents=True)
        field.write_text("field\n", encoding="utf-8")
    partial = case / "processor0" / "2" / "U"
    partial.parent.mkdir(parents=True)
    partial.write_text("field\n", encoding="utf-8")

    payload = progress_evidence(case, process_live=True)

    assert payload["state"] == "PARTIAL_CHECKPOINT"
    assert payload["partial_checkpoint_times"][0]["time"] == "2"
    assert payload["reason_codes"][-1] == "PARTIAL_CHECKPOINT"
