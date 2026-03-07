from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from ofti.app import cli_tools


def _ns(**kwargs: object) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_knife_doctor_json_and_ok_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {"case": "case", "lines": ["line"], "errors": [], "warnings": []}
    monkeypatch.setattr(cli_tools.knife_ops, "doctor_payload", lambda _case: payload)
    monkeypatch.setattr(cli_tools.knife_ops, "doctor_exit_code", lambda _payload: 0)

    assert cli_tools._knife_doctor(_ns(case_dir=Path(), json=True)) == 0
    assert json.loads(capsys.readouterr().out)["case"] == "case"

    assert cli_tools._knife_doctor(_ns(case_dir=Path(), json=False)) == 0
    assert "OK: no issues found." in capsys.readouterr().out


def test_knife_plain_and_json_branches(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.knife_ops,
        "preflight_payload",
        lambda _case: {
            "case": "case",
            "checks": {"system/controlDict": True},
            "solver_error": "missing app",
            "ok": False,
        },
    )
    assert cli_tools._knife_preflight(_ns(case_dir=Path(), json=False)) == 1
    assert "solver_error=missing app" in capsys.readouterr().out

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "compare_payload",
        lambda *_a, **_k: {
            "left_case": "left",
            "right_case": "right",
            "diff_count": 1,
            "diffs": [
                {
                    "rel_path": "system/controlDict",
                    "kind": "dict",
                    "error": None,
                    "missing_in_left": ["x"],
                    "missing_in_right": ["y"],
                    "value_diffs": [{"key": f"k{idx}", "left": str(idx), "right": str(idx + 1)} for idx in range(41)],
                    "left_hash": "abc",
                    "right_hash": "def",
                },
            ],
        },
    )
    assert cli_tools._knife_compare(_ns(left_case=Path("a"), right_case=Path("b"), json=True)) == 0
    assert json.loads(capsys.readouterr().out)["diff_count"] == 1

    assert cli_tools._knife_compare(_ns(left_case=Path("a"), right_case=Path("b"), json=False)) == 0
    out = capsys.readouterr().out
    assert "missing_in_left: x" in out
    assert "missing_in_right: y" in out
    assert "value_diff k0" in out
    assert "value_diff_more=1" in out
    assert "left_hash=abc" in out
    assert "right_hash=def" in out

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "status_payload",
        lambda _case: {
            "case": "case",
            "latest_time": "2",
            "latest_iteration": 12,
            "latest_delta_t": 0.1,
            "sec_per_iter": 0.2,
            "solver_error": "broken",
            "solver": None,
            "solver_status": None,
            "run_time_control": {"criteria": [], "passed": 0, "failed": 0, "unknown": 0},
            "eta_seconds_to_criteria_start": None,
            "eta_seconds_to_end_time": None,
            "log_path": "log",
            "log_fresh": False,
            "running": False,
            "tracked_solver_processes": [{"pid": 1}],
            "untracked_solver_processes": [{"pid": 2}],
            "jobs_running": 1,
            "jobs_total": 2,
        },
    )
    assert cli_tools._knife_status(_ns(case_dir=Path(), json=True)) == 0
    assert json.loads(capsys.readouterr().out)["solver_error"] == "broken"
    assert cli_tools._knife_status(_ns(case_dir=Path(), json=False)) == 0
    out = capsys.readouterr().out
    assert "solver_error=broken" in out
    assert "tracked_solver_processes=1" in out
    assert "untracked_solver_processes=1" in out

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "current_payload",
        lambda _case: {
            "case": "case",
            "solver_error": "bad solver",
            "solver": None,
            "jobs": [],
            "untracked_processes": [],
        },
    )
    assert cli_tools._knife_current(_ns(case_dir=Path(), json=True)) == 0
    assert json.loads(capsys.readouterr().out)["solver_error"] == "bad solver"
    assert cli_tools._knife_current(_ns(case_dir=Path(), json=False)) == 0
    out = capsys.readouterr().out
    assert "solver_error=bad solver" in out
    assert "No tracked running jobs." in out
    assert "untracked_solver_processes=none" in out


def test_converge_plot_residuals_and_watch_external(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_tools.knife_ops, "converge_payload", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad converge")))
    args = _ns(
        source=Path("log"),
        strict=False,
        shock_drift_limit=0.1,
        drag_band_limit=0.1,
        mass_limit=0.1,
        json=False,
    )
    assert cli_tools._knife_converge(args) == 1
    assert "ofti: bad converge" in capsys.readouterr().err

    monkeypatch.setattr(
        cli_tools.plot_ops,
        "residuals_payload",
        lambda *_a, **_k: {
            "log": "log.simpleFoam",
            "fields": [{"field": "p", "count": 2, "last": 1.0, "min": 0.2, "max": 1.0}],
        },
    )
    assert cli_tools._plot_residuals(_ns(source=Path(), field=[], limit=0, json=False)) == 0
    assert "p: count=2 last=1" in capsys.readouterr().out

    monkeypatch.setattr(
        cli_tools.watch_ops,
        "external_watch_payload",
        lambda *_a, **_k: {
            "case": "/case",
            "command": ["python", "watcher.py"],
            "dry_run": True,
            "ok": True,
        },
    )
    assert cli_tools._watch_external(_ns(case_dir=Path("/case"), command=["python", "watcher.py"], dry_run=True, json=False)) == 0
    out = capsys.readouterr().out
    assert "command=['python', 'watcher.py']" in out
    assert "dry_run=True" in out


def test_watch_stop_signal_and_pause_resume_handlers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "stop_payload",
        lambda *_a, **_k: {
            "case": "case",
            "signal": _k.get("signal_name", "TERM"),
            "selected": 1,
            "stopped": [{"id": "1", "pid": 10, "name": "solver"}],
            "failed": [],
        },
    )
    args = _ns(case_dir=Path(), job_id=None, name=None, all=False, signal="INT", json=False)
    assert cli_tools._watch_stop(args) == 0
    out = capsys.readouterr().out
    assert "signal=INT" in out
    assert "stopped:" in out

    assert cli_tools._watch_stop(_ns(case_dir=Path(), job_id=None, name=None, all=False, signal="TERM", json=True)) == 0
    assert json.loads(capsys.readouterr().out)["signal"] == "TERM"

    monkeypatch.setattr(
        cli_tools.watch_ops,
        "pause_payload",
        lambda *_a, **_k: {
            "case": "case",
            "selected": 1,
            "paused": [{"id": "1", "pid": 10, "name": "solver"}],
            "failed": [],
        },
    )
    assert cli_tools._watch_pause(_ns(case_dir=Path(), job_id=None, name=None, all=False, json=False)) == 0
    assert "paused:" in capsys.readouterr().out

    monkeypatch.setattr(
        cli_tools.watch_ops,
        "resume_payload",
        lambda *_a, **_k: {
            "case": "case",
            "selected": 1,
            "resumed": [{"id": "1", "pid": 10, "name": "solver"}],
            "failed": [{"id": "2", "pid": 20, "error": "gone"}],
        },
    )
    assert cli_tools._watch_resume(_ns(case_dir=Path(), job_id=None, name=None, all=False, json=False)) == 1
    out = capsys.readouterr().out
    assert "resumed:" in out
    assert "failed:" in out
