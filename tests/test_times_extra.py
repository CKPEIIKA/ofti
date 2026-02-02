from __future__ import annotations

from pathlib import Path

from ofti.core import times


def test_time_directories_sorted(tmp_path: Path) -> None:
    for name in ("2", "0.5", "10"):
        (tmp_path / name).mkdir()
    (tmp_path / "system").mkdir()

    dirs = times.time_directories(tmp_path)
    assert [d.name for d in dirs] == ["0.5", "2", "10"]


def test_latest_time_falls_back_when_command_missing(tmp_path: Path, monkeypatch) -> None:
    for name in ("0", "3.5", "2"):
        (tmp_path / name).mkdir()

    def raise_oserror(*_args, **_kwargs):
        raise OSError("no foamListTimes")

    monkeypatch.setattr(times, "run_trusted", raise_oserror)

    assert times.latest_time(tmp_path) == "3.5"
