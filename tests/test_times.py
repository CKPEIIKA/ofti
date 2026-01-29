from pathlib import Path
from unittest import mock

from ofti.core.times import latest_time, time_directories


def test_time_directories_sorted(tmp_path: Path) -> None:
    (tmp_path / "0.1").mkdir()
    (tmp_path / "2").mkdir()
    (tmp_path / "1.5").mkdir()
    times = time_directories(tmp_path)
    assert [p.name for p in times] == ["0.1", "1.5", "2"]


def test_latest_time_fallback(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "0").mkdir()
    (tmp_path / "1").mkdir()
    monkeypatch.setattr("ofti.core.times.run_trusted", mock.Mock(side_effect=OSError))
    assert latest_time(tmp_path) == "1"
