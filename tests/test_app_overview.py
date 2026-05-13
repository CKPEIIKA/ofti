from __future__ import annotations

from pathlib import Path

import pytest

from ofti.app import overview
from ofti.ui_curses import layout


def test_overview_text_aggregates_readonly_sections(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        overview.knife_ops,
        "preflight_payload",
        lambda _case: {
            "ok": True,
            "checks": {"system/controlDict": True, "solver_entry": True},
            "solver_error": None,
        },
    )
    monkeypatch.setattr(
        overview.knife_ops,
        "doctor_payload",
        lambda _case: {"errors": [], "warnings": ["mesh missing"]},
    )
    monkeypatch.setattr(
        overview.knife_ops,
        "status_payload",
        lambda *_a, **_k: {
            "case": str(tmp_path),
            "latest_time": 1.0,
            "latest_iteration": 12,
            "latest_delta_t": 0.1,
            "sec_per_iter": 0.2,
            "solver": "simpleFoam",
            "solver_error": None,
            "solver_status": "running",
            "run_time_control": {"criteria": [], "passed": 0, "failed": 0, "unknown": 0},
            "eta_seconds_to_criteria_start": None,
            "eta_seconds_to_end_time": 30,
            "log_path": str(tmp_path / "log.simpleFoam"),
            "log_fresh": True,
            "running": True,
            "jobs_running": 1,
            "jobs_total": 1,
            "tracked_solver_processes": [],
            "untracked_solver_processes": [],
        },
    )
    monkeypatch.setattr(
        overview.knife_ops,
        "current_payload",
        lambda *_a, **_k: {
            "jobs_running": 1,
            "jobs_total": 1,
            "jobs": [{"id": "j1", "pid": 123, "name": "simpleFoam", "status": "running"}],
            "untracked_processes": [],
        },
    )
    monkeypatch.setattr(
        overview.knife_ops,
        "eta_payload",
        lambda *_a, **_k: {
            "eta_mode": "end",
            "eta_reason": "endTime",
            "eta_confidence": "medium",
            "eta_seconds": 30,
            "eta_criteria_seconds": None,
            "eta_end_time_seconds": 30,
        },
    )
    monkeypatch.setattr(
        overview.plot_ops,
        "metrics_payload",
        lambda _case: {
            "log": "log.simpleFoam",
            "times": {"count": 2, "last": 1.0},
            "courant": {"count": 2, "max": 0.5},
            "execution_time": {
                "count": 2,
                "last": 4.0,
                "delta_min": 1.0,
                "delta_avg": 1.5,
                "delta_max": 2.0,
            },
            "residual_fields": ["Ux"],
        },
    )
    monkeypatch.setattr(
        overview.plot_ops,
        "residuals_payload",
        lambda *_a, **_k: {
            "log": "log.simpleFoam",
            "fields": [{"field": "Ux", "count": 2, "last": 1e-4, "min": 1e-4, "max": 1e-3}],
        },
    )
    monkeypatch.setattr(
        overview.knife_ops,
        "initials_payload",
        lambda _case: {"field_count": 2, "patch_count": 4},
    )
    monkeypatch.setattr(
        overview,
        "case_dna_payload",
        lambda *_a, **_k: {
            "case": str(tmp_path),
            "risk": "low",
            "residual_fields": ["Ux"],
            "fingerprint": {"hash": "abc", "files": 0, "skipped": 0},
        },
    )
    monkeypatch.setattr(
        overview,
        "mission_scope_payload",
        lambda _case: {"rows": [{"scope": "Courant max", "value": 0.5, "plot": "████"}]},
    )
    monkeypatch.setattr(
        overview,
        "lint_payload",
        lambda _case: {
            "case": str(tmp_path),
            "errors": 0,
            "warnings": 1,
            "info": 0,
            "findings": [
                {
                    "severity": "WARN",
                    "rule": "pressure-reference",
                    "message": "missing pRefCell",
                    "evidence": "system/fvSolution",
                    "advice": "add pRefCell",
                },
            ],
        },
    )
    monkeypatch.setattr(
        overview.watch_ops,
        "log_tail_payload",
        lambda *_a, **_k: {
            "log": "log.simpleFoam",
            "lines": [
                "Time = 1",
                "smoothSolver: Solving for Ux, Initial residual = 1e-4",
                "Courant Number mean: 0.2 max: 0.5",
                "ExecutionTime = 4 s",
            ],
        },
    )

    text = overview.overview_text(tmp_path)

    assert "Case DNA" in text
    assert "Mission Scopes" in text
    assert "Mesh Radar" in text
    assert "Resource Watch" in text
    assert "Case Lint" in text
    assert "Alert Cards" in text
    assert "Case doctor warnings" in text
    assert "Runtime Status" in text
    assert "Live Jobs And Processes" in text
    assert "Live Cases Monitor" in text
    assert "Log + Residual Split View" in text
    assert "Folded Log" in text
    assert "Log metrics" in text
    assert "Residuals" in text
    assert "Tracked jobs" in text
    assert "j1" in text
    assert "123" in text
    assert "residual_fields" in text
    assert "Ux" in text
    assert "Count" in text
    assert "Courant max" in text
    assert "fingerprint" in text
    assert "pressure-reference" in text
    assert "Signals" in text

    deck = "\n".join(overview.cockpit_lines(tmp_path, width=100))
    assert "OFTI CAPTAINS DECK" in deck
    assert "Mission scopes" in deck
    assert "Live cases" in deck
    assert "Case lint" in deck
    assert "Log radar" in deck
    assert ">> Alerts" in "\n".join(overview.cockpit_lines(tmp_path, width=100, selected_panel=2))
    assert "Flight" in overview.cockpit_panel_names()
    assert "solver_status" in "\n".join(overview.cockpit_panel_detail_lines(tmp_path, "Flight"))


def test_running_header_metadata_and_banner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    meta = {
        "case_name": "case",
        "case_path": str(tmp_path),
        "solver": "simpleFoam",
        "foam_version": "v2312",
        "case_header_version": "v2312",
        "latest_time": "1",
        "status": "ran",
        "mesh": "mesh",
        "cells": "10",
        "faces": "20",
        "points": "30",
        "disk": "1KB",
        "parallel": "serial",
        "log": "log.simpleFoam",
    }
    monkeypatch.setattr(
        overview.knife_ops,
        "status_payload",
        lambda *_a, **_k: {
            "running": True,
            "jobs_running": 1,
            "jobs_tracked_running": 1,
            "tracked_solver_processes": [{"pid": 1}],
            "untracked_solver_processes": [{"pid": 2}],
            "latest_iteration": 7,
            "latest_delta_t": 0.01,
            "sec_per_iter": 0.2,
            "eta_seconds_to_end_time": 10,
            "eta_seconds_to_criteria_start": 5,
            "log_fresh": True,
        },
    )

    enriched = overview.running_header_metadata(tmp_path, meta)
    banner = "\n".join(layout.case_banner_lines(enriched))

    assert enriched["running"] == "yes"
    assert "Running: jobs=1 pids=2" in banner
    assert "ETA end=10 criteria=5" in banner


def test_overview_branches_for_errors_and_empty_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    meta = {"case_name": "case"}

    monkeypatch.setattr(
        overview.knife_ops,
        "status_payload",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad status")),
    )
    assert overview.running_header_metadata(tmp_path, meta) is meta
    assert "unavailable: bad status" in overview._safe_section(
        "Status",
        lambda: overview._status_lines(tmp_path),
    )

    monkeypatch.setattr(
        overview.knife_ops,
        "preflight_payload",
        lambda _case: {"ok": False, "checks": [], "solver_error": "missing solver"},
    )
    preflight_lines = overview._preflight_lines(tmp_path)
    assert "solver" in "\n".join(preflight_lines)
    assert "missing solver" in "\n".join(preflight_lines)

    monkeypatch.setattr(
        overview.knife_ops,
        "doctor_payload",
        lambda _case: {"errors": [f"e{i}" for i in range(22)], "warnings": [f"w{i}" for i in range(22)]},
    )
    doctor_lines = overview._doctor_lines(tmp_path)
    assert "errors_more=2" in doctor_lines
    assert "warnings_more=2" in doctor_lines

    calls = {"count": 0}

    def _current_payload(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TypeError("old signature")
        return {
            "jobs_running": 1,
            "jobs_total": 1,
            "proc_access_warning": "proc warning",
            "jobs": [],
            "untracked_processes": [
                {"pid": 2, "role": "solver", "solver": "simpleFoam", "launcher_pid": None},
            ],
        }

    monkeypatch.setattr(overview.knife_ops, "current_payload", _current_payload)
    current_lines = overview._current_lines(tmp_path)
    current_text = "\n".join(current_lines)
    assert "proc_access_warning" in current_text
    assert "proc warning" in current_text
    assert "Untracked solver processes" in current_lines

    monkeypatch.setattr(
        overview.knife_ops,
        "doctor_payload",
        lambda _case: {"errors": [], "warnings": []},
    )
    monkeypatch.setattr(
        overview.knife_ops,
        "status_payload",
        lambda *_a, **_k: {
            "running": True,
            "log_fresh": True,
            "run_time_control": {"failed": 0},
        },
    )
    monkeypatch.setattr(
        overview.plot_ops,
        "metrics_payload",
        lambda _case: {"log": "log.simpleFoam", "courant": {"max": 1.5}},
    )
    monkeypatch.setattr(
        overview.plot_ops,
        "residuals_payload",
        lambda *_a, **_k: {"log": "log.simpleFoam", "fields": [{"field": "U"}]},
    )
    alert_text = "\n".join(overview._alert_lines(tmp_path))
    assert "High Courant number" in alert_text

    monkeypatch.setattr(
        overview.plot_ops,
        "metrics_payload",
        lambda _case: {
            "log": "log.simpleFoam",
            "times": [],
            "courant": [],
            "execution_time": [],
            "residual_fields": [],
        },
    )
    assert "time_steps" in "\n".join(overview._log_metrics_lines(tmp_path))

    monkeypatch.setattr(
        overview.plot_ops,
        "residuals_payload",
        lambda *_a, **_k: {"log": "log.simpleFoam", "fields": []},
    )
    assert "No residuals found." in overview._residual_lines(tmp_path)
    split = "\n".join(overview._log_residual_split_lines(tmp_path))
    assert "Log metrics" in split
    assert "Residuals" in split

    monkeypatch.setattr(
        overview.knife_ops,
        "initials_payload",
        lambda _case: (_ for _ in ()).throw(ValueError("bad initials")),
    )
    monkeypatch.setattr(
        overview,
        "case_dna_payload",
        lambda *_a, **_k: {"case": str(tmp_path), "risk": "medium", "fingerprint": {"hash": "abc"}},
    )
    dna = "\n".join(overview._case_dna_lines(tmp_path))
    assert "risk" in dna

    monkeypatch.setattr(
        overview,
        "lint_payload",
        lambda _case: {"case": str(tmp_path), "errors": 0, "warnings": 0, "info": 0, "findings": []},
    )
    assert "OK" in "\n".join(overview._lint_lines(tmp_path))

    monkeypatch.setattr(
        overview.watch_ops,
        "log_tail_payload",
        lambda *_a, **_k: {"log": "log.simpleFoam", "lines": ["Time = 1", "noise"]},
    )
    assert "folded" in "\n".join(overview._folded_log_lines(tmp_path))
