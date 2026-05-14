from __future__ import annotations

import types
from pathlib import Path

from ofti.foam import times


def test_foam_latest_time_uses_foam_list_times(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        times,
        "run_trusted",
        lambda *_args, **_kwargs: types.SimpleNamespace(returncode=0, stdout="7\n"),
    )

    assert times.latest_time(tmp_path) == "7"


def test_foam_latest_time_falls_back_to_scan(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "3").mkdir()
    monkeypatch.setattr(
        times,
        "run_trusted",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")),
    )

    assert times.latest_time(tmp_path) == "3"
