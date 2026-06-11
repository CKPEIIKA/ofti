from pathlib import Path

import pytest

from ofti.app import cli


def test_deck_falls_back_to_curses_without_textual(monkeypatch, capsys, tmp_path: Path) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr("ofti.ui_textual.textual_available", lambda: False)
    def fake_run_tui(case: str, debug: bool = False) -> None:
        seen.update(case=case, debug=debug)

    monkeypatch.setattr(cli, "run_tui", fake_run_tui)

    assert cli.main(["tui", str(tmp_path)]) == 0
    assert seen["case"] == str(tmp_path)
    err = capsys.readouterr().err
    assert "ofti[tui]" in err
    assert "curses" in err


def test_deck_launches_mission_control_with_textual(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("textual")
    seen: dict[str, object] = {}

    def fake_run(case_path: Path, *, interval: float) -> int:
        seen.update(case=case_path, interval=interval)
        return 0

    monkeypatch.setattr("ofti.ui_textual.textual_available", lambda: True)
    monkeypatch.setattr("ofti.ui_textual.app.run_mission_control", fake_run)

    assert cli.main(["tui", str(tmp_path), "--interval", "1.5"]) == 0
    assert seen == {"case": Path(str(tmp_path)), "interval": 1.5}


def test_deck_reports_errors(monkeypatch, capsys, tmp_path: Path) -> None:
    pytest.importorskip("textual")

    def boom(case_path: Path, *, interval: float) -> int:
        raise RuntimeError("deck exploded")

    monkeypatch.setattr("ofti.ui_textual.textual_available", lambda: True)
    monkeypatch.setattr("ofti.ui_textual.app.run_mission_control", boom)

    assert cli.main(["tui", str(tmp_path)]) == 1
    assert "deck exploded" in capsys.readouterr().err
