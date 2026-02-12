from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ofti.app.menus.postprocessing import postprocessing_menu
from ofti.app.state import AppState


def test_postprocessing_menu_no_duplicate_entries(monkeypatch, tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    (case_path / "system").mkdir(parents=True)

    captured: dict[str, list[str]] = {}

    def fake_menu_choice(
        _stdscr,
        _title,
        options,
        _state,
        _menu_key,
        **_kwargs,
    ):
        captured["options"] = list(options)
        return -1

    monkeypatch.setattr("ofti.app.menus.postprocessing.menu_choice", fake_menu_choice)

    postprocessing_menu(
        stdscr=object(),
        case_path=case_path,
        state=AppState(),
        command_handler=SimpleNamespace(),
        command_suggestions=SimpleNamespace(),
    )

    options = captured["options"]
    assert "View logs" in options
    assert "Log analysis summary" not in options
    assert "postProcess" not in options
