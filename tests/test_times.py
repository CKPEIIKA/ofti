from pathlib import Path
from unittest import mock

from ofti.core.times import latest_time, time_directories
from ofti.foam import times as foam_times


def test_time_directories_sorted(tmp_path: Path) -> None:
    (tmp_path / "0.1").mkdir()
    (tmp_path / "2").mkdir()
    (tmp_path / "1.5").mkdir()
    times = time_directories(tmp_path)
    assert [p.name for p in times] == ["0.1", "1.5", "2"]


def test_latest_time_is_filesystem_only(tmp_path: Path) -> None:
    # core.times is pure: no subprocess, just the filesystem scan.
    (tmp_path / "0").mkdir()
    (tmp_path / "1").mkdir()
    assert latest_time(tmp_path) == "1"


def test_foam_latest_time_uses_foamlisttimes_then_scan(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "0").mkdir()
    (tmp_path / "1").mkdir()

    # foamListTimes wins when it returns a value.
    monkeypatch.setattr(
        foam_times,
        "run_trusted",
        lambda *_a, **_k: mock.Mock(returncode=0, stdout="5\n"),
    )
    assert foam_times.latest_time(tmp_path) == "5"

    # Falls back to the pure core scan when the command is unavailable.
    monkeypatch.setattr(foam_times, "run_trusted", mock.Mock(side_effect=OSError))
    assert foam_times.latest_time(tmp_path) == "1"
