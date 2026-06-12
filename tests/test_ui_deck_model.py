from pathlib import Path

from ofti.ui import deck


def test_deck_registry_is_consistent() -> None:
    tab_ids = {tab_id for tab_id, _ in deck.DECK_TABS}
    assert tab_ids == {panel.tab_id for panel in deck.DECK_PANELS}
    panel_ids = [panel.panel_id for panel in deck.DECK_PANELS]
    assert len(panel_ids) == len(set(panel_ids))
    for tab_id, _label in deck.DECK_TABS:
        assert deck.tab_panels(tab_id), f"tab {tab_id} has no panels"
    for panel in deck.DECK_PANELS:
        assert panel.description, f"panel {panel.panel_id} has no description"


def test_env_status_states(monkeypatch) -> None:
    monkeypatch.setattr("ofti.ui.deck.environment_loaded", lambda: False)
    loaded, label = deck.env_status()
    assert loaded is False
    assert "not loaded" in label
    assert "▲" in label

    monkeypatch.setattr("ofti.ui.deck.environment_loaded", lambda: True)
    monkeypatch.setenv("WM_PROJECT_VERSION", "v2412")
    loaded, label = deck.env_status()
    assert loaded is True
    assert "v2412" in label
    assert "✓" in label


def test_case_candidates_lists_current_and_nearby(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ofti.ui.deck.scan_proc_solver_processes", lambda *_a, **_k: [])
    current = tmp_path / "cavity"
    (current / "system").mkdir(parents=True)
    (current / "system" / "controlDict").write_text("application icoFoam;\n")
    sibling = tmp_path / "cavity-fine"
    (sibling / "system").mkdir(parents=True)
    (sibling / "system" / "controlDict").write_text("application icoFoam;\n")
    (tmp_path / "not-a-case").mkdir()

    from_root = deck.case_candidates(tmp_path)
    assert [c.kind for c in from_root] == ["nearby", "nearby"]
    assert {c.path for c in from_root} == {current.resolve(), sibling.resolve()}

    from_case = deck.case_candidates(current)
    assert from_case[0].kind == "current"
    assert from_case[0].path == current.resolve()


def test_status_strip_flags_non_case_dir(tmp_path: Path) -> None:
    strip = deck.status_strip(tmp_path)
    assert "not an OpenFOAM case" in strip
    assert "▲" in strip


def test_collect_deck_update_placeholder_for_non_case(tmp_path: Path) -> None:
    update = deck.collect_deck_update(tmp_path, "cockpit")
    for lines in update.panels.values():
        assert any("Not an OpenFOAM case" in line for line in lines)


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
    _write_control_dict(tmp_path)
    strip = deck.status_strip(tmp_path)
    assert strip.startswith(f"case:{tmp_path.name}")
    assert "t=" in strip
    assert "env" in strip


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


def test_flight_updates_for_actions() -> None:
    assert deck.flight_updates_for("safe-stop") == {"stopAt": "writeNow"}
    assert deck.flight_updates_for("write-now") == {"stopAt": "writeNow"}
    assert deck.flight_updates_for("deltaT", "0.0005") == {"deltaT": "0.0005"}
    assert deck.flight_updates_for("endTime", " 2.0 ") == {"endTime": "2.0"}
    assert deck.flight_updates_for("deltaT", "") == {}
    assert deck.flight_updates_for("deltaT", None) == {}
    assert deck.flight_updates_for("bogus") == {}


def _write_control_dict(case: Path) -> Path:
    system = case / "system"
    system.mkdir(parents=True, exist_ok=True)
    control = system / "controlDict"
    control.write_text(
        "FoamFile\n{\n    object controlDict;\n}\n"
        "application simpleFoam;\n"
        "stopAt endTime;\n"
        "endTime 1.0;\n"
        "deltaT 0.001;\n"
        "writeInterval 0.05;\n",
    )
    return control


def test_runtime_edit_preview_and_apply(tmp_path: Path) -> None:
    control = _write_control_dict(tmp_path)

    preview = "\n".join(deck.runtime_edit_preview(tmp_path, {"endTime": "2.0"}))
    assert "applied=False" in preview
    assert "endTime" in preview
    assert "2.0" in preview
    assert "endTime 1.0;" in control.read_text()

    applied = "\n".join(deck.runtime_edit_apply(tmp_path, {"endTime": "2.0"}))
    assert "applied=True" in applied
    assert "snapshot=" in applied
    assert "2.0" in control.read_text()


def test_runtime_edit_preview_rejects_unsafe_keys(tmp_path: Path) -> None:
    _write_control_dict(tmp_path)
    lines = "\n".join(deck.runtime_edit_preview(tmp_path, {"application": "rm -rf"}))
    assert "error=" in lines
    assert "unsupported" in lines
