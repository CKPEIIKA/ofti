from pathlib import Path

from ofti.ui import deck


def test_deck_registry_is_consistent() -> None:
    tab_ids = {tab_id for tab_id, _ in deck.DECK_TABS}
    assert tab_ids == {panel.tab_id for panel in deck.DECK_PANELS}
    panel_ids = [panel.panel_id for panel in deck.DECK_PANELS]
    assert len(panel_ids) == len(set(panel_ids))
    for tab_id, _label in deck.DECK_TABS:
        assert deck.tab_panels(tab_id), f"tab {tab_id} has no panels"


def test_collect_tab_lines_is_safe_on_empty_case(tmp_path: Path) -> None:
    for tab_id, _label in deck.DECK_TABS:
        results = deck.collect_tab_lines(tmp_path, tab_id)
        assert set(results) == {panel.panel_id for panel in deck.tab_panels(tab_id)}
        for lines in results.values():
            assert isinstance(lines, list)
            assert all(isinstance(line, str) for line in lines)


def test_collect_cockpit_lines_on_example_case() -> None:
    case = Path(__file__).resolve().parent.parent / "examples" / "wedge_sphere"
    results = deck.collect_tab_lines(case, "cockpit")
    dna_text = "\n".join(results["dna"])
    assert "solver" in dna_text
    assert "hy2Foam" in dna_text


def test_panel_lines_unknown_panel(tmp_path: Path) -> None:
    from ofti.tools.captains_deck_service import CaptainsDeckData

    lines = deck.panel_lines(CaptainsDeckData(tmp_path), "nope")
    assert lines == ["unknown panel: nope"]


def test_status_strip_uses_quick_metadata(tmp_path: Path) -> None:
    strip = deck.status_strip(tmp_path)
    assert strip.startswith(f"case:{tmp_path.name}")
    assert "t=" in strip


def test_collect_deck_update_bundles_status_and_panels(tmp_path: Path) -> None:
    update = deck.collect_deck_update(tmp_path, "doctor")
    assert update.status.startswith("case:")
    assert set(update.panels) == {"doctor", "lint"}


def test_line_severity_classification() -> None:
    assert deck.line_severity("gate    NO-GO") == "crit"
    assert deck.line_severity("checkMesh FAIL") == "crit"
    assert deck.line_severity("WARN: high Courant") == "warn"
    assert deck.line_severity("log unavailable: missing") == "warn"
    assert deck.line_severity("mesh OK") == "ok"
    assert deck.line_severity("latest_time 0.5") is None
