from __future__ import annotations

from pathlib import Path

from ofti.tools import cockpit_service


def test_case_dna_payload_uses_shared_readonly_sources(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cockpit_service.knife_service,
        "preflight_payload",
        lambda _case: {"ok": True, "solver": "simpleFoam"},
    )
    monkeypatch.setattr(
        cockpit_service.knife_service,
        "status_payload",
        lambda *_a, **_k: {
            "solver": "simpleFoam",
            "running": True,
            "run_time_control": {"failed": 0},
            "jobs_running": 1,
        },
    )
    monkeypatch.setattr(
        cockpit_service.plot_service,
        "metrics_payload",
        lambda _case: {"residual_fields": ["Ux"]},
    )
    monkeypatch.setattr(
        cockpit_service.knife_service,
        "initials_payload",
        lambda _case: {"field_count": 2, "patch_count": 3},
    )

    payload = cockpit_service.case_dna_payload(tmp_path)

    assert payload["risk"] == "low"
    assert payload["fields"] == 2
    assert payload["fingerprint"]["hash"]


def test_mission_scope_payload_builds_dashboard_rows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cockpit_service.plot_service,
        "metrics_payload",
        lambda _case: {
            "courant": {"max": 0.5},
            "execution_time": {"delta_min": 1, "delta_avg": 2, "delta_max": 3},
        },
    )
    monkeypatch.setattr(
        cockpit_service.plot_service,
        "residuals_payload",
        lambda *_a, **_k: {"fields": [{"field": "Ux", "last": 1e-4, "min": 1e-4, "max": 1e-3}]},
    )

    payload = cockpit_service.mission_scope_payload(tmp_path)

    text = "\n".join(str(row) for row in payload["rows"])
    assert "Courant max" in text
    assert "Residual Ux" in text


def test_cockpit_payload_degrades_when_logs_are_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cockpit_service.knife_service,
        "preflight_payload",
        lambda _case: {"ok": True, "solver": "simpleFoam"},
    )
    monkeypatch.setattr(
        cockpit_service.knife_service,
        "status_payload",
        lambda *_a, **_k: {"solver": "simpleFoam", "run_time_control": {"failed": 0}},
    )
    monkeypatch.setattr(
        cockpit_service.knife_service,
        "initials_payload",
        lambda _case: (_ for _ in ()).throw(ValueError("no initials")),
    )
    monkeypatch.setattr(
        cockpit_service.plot_service,
        "metrics_payload",
        lambda _case: (_ for _ in ()).throw(ValueError("no log")),
    )
    monkeypatch.setattr(
        cockpit_service.plot_service,
        "residuals_payload",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("no log")),
    )

    payload = cockpit_service.cockpit_payload(tmp_path)

    assert payload["case_dna"]["risk"] == "medium"
    assert payload["case_dna"]["fingerprint"]["hash"]
    assert payload["scopes"]["rows"] == [
        {"scope": "Log metrics", "value": "unavailable", "plot": "no log"},
    ]
