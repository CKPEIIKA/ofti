from __future__ import annotations

from ofti.tools.alert_service import overview_alert_cards


def test_overview_alert_cards_collects_existing_warnings() -> None:
    cards = overview_alert_cards(
        preflight={"ok": False, "solver_error": "missing application", "checks": {}},
        doctor={"errors": ["bad mesh"], "warnings": ["weak BC"]},
        status={
            "running": True,
            "log_fresh": False,
            "log_path": "log.simpleFoam",
            "run_time_control": {"failed": 1},
            "proc_access_warning": "proc hidden",
        },
        metrics={"courant": {"max": 1.2}},
        residuals={"log": "log.simpleFoam", "fields": []},
    )

    titles = {str(card["title"]) for card in cards}
    assert "Preflight failed" in titles
    assert "Case doctor errors" in titles
    assert "High Courant number" in titles
    assert {str(card["severity"]) for card in cards} >= {"CRIT", "WARN", "INFO"}
