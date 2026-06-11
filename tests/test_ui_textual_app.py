import asyncio
from pathlib import Path

import pytest

textual = pytest.importorskip("textual")

from ofti.ui import deck as deck_model  # noqa: E402
from ofti.ui_textual.app import HelpScreen, MissionControlApp, styled_lines  # noqa: E402


def _fake_update(_case_path: Path, tab_id: str) -> deck_model.DeckUpdate:
    return deck_model.DeckUpdate(
        status="case:fake  simpleFoam  ran  t=0.5",
        panels={
            panel.panel_id: [f"{panel.panel_id} content", "gate NO-GO", "mesh OK"]
            for panel in deck_model.tab_panels(tab_id)
        },
    )


async def _panel_text(app: MissionControlApp, pilot, panel_id: str) -> str:
    for _ in range(100):
        text = str(app.query_one(f"#body-{panel_id}").render())
        if text and not text.startswith("loading"):
            return text
        await pilot.pause(0.05)
    raise AssertionError(f"panel {panel_id} never loaded")


def test_styled_lines_severity_markup() -> None:
    text = styled_lines(["gate NO-GO", "WARN x", "mesh OK", "plain"])
    rendered = text.plain.splitlines()
    assert rendered == ["gate NO-GO", "WARN x", "mesh OK", "plain"]
    styles = {span.style for span in text.spans}
    assert "bold red" in styles
    assert "yellow" in styles
    assert "green" in styles


def test_mission_control_panels_tabs_help_and_quit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ofti.ui.deck.collect_deck_update", _fake_update)

    async def scenario() -> None:
        app = MissionControlApp(tmp_path, interval=0)
        async with app.run_test(size=(120, 40)) as pilot:
            assert "dna content" in await _panel_text(app, pilot, "dna")
            status = str(app.query_one("#status-bar").render())
            assert "case:fake" in status
            panel = app.query_one("#panel-dna")
            assert "updated" in str(panel.border_subtitle)

            await pilot.press("right")
            assert app.active_tab_id() == "checklist"
            assert "checklist content" in await _panel_text(app, pilot, "checklist")
            await pilot.press("left")
            assert app.active_tab_id() == "cockpit"

            await pilot.press("3")
            assert app.active_tab_id() == "flight"
            await pilot.press("1")
            assert app.active_tab_id() == "cockpit"

            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)

            await pilot.press("r")
            assert "dna content" in await _panel_text(app, pilot, "dna")
            await pilot.press("q")
        assert app.return_value == 0

    asyncio.run(scenario())


def test_cockpit_grid_narrow_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ofti.ui.deck.collect_deck_update", _fake_update)

    async def scenario() -> None:
        app = MissionControlApp(tmp_path, interval=0)
        async with app.run_test(size=(84, 30)) as pilot:
            await pilot.pause()
            assert app.query_one("#cockpit-grid").has_class("narrow")
            await pilot.press("q")

    asyncio.run(scenario())


def test_run_mission_control_uses_app(monkeypatch, tmp_path: Path) -> None:
    from ofti.ui_textual import app as app_module

    calls: dict[str, object] = {}

    class FakeApp:
        def __init__(self, case_path: Path, *, interval: float) -> None:
            calls["case"] = case_path
            calls["interval"] = interval

        def run(self) -> int:
            calls["ran"] = True
            return 0

    monkeypatch.setattr(app_module, "MissionControlApp", FakeApp)
    assert app_module.run_mission_control(tmp_path, interval=1.5) == 0
    assert calls == {"case": tmp_path, "interval": 1.5, "ran": True}
