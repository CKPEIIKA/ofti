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

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "adopt_payload",
        lambda _case: {
            "case": "case",
            "selected": 1,
            "adopted": [{"id": "1-777", "pid": 777, "name": "hy2Foam", "role": "solver"}],
            "failed": [],
            "skipped": [],
            "jobs_running_before": 0,
            "jobs_running_after": 1,
        },
    )
    assert cli_tools._knife_adopt(_ns(case_dir=Path(), json=True)) == 0
    assert json.loads(capsys.readouterr().out)["selected"] == 1
    assert cli_tools._knife_adopt(_ns(case_dir=Path(), json=False)) == 0
    out = capsys.readouterr().out
    assert "adopted=1" in out
    assert "adopted_rows:" in out


def test_receipt_handlers_and_run_solver_recording(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "receipt.json"
    restored_dir = tmp_path / "restored"
    restored_receipt = restored_dir / ".ofti" / "restored_from_receipt.json"
    monkeypatch.setattr(
        cli_tools.receipt_ops,
        "write_case_run_receipt",
        lambda *_a, **_k: receipt_path,
    )
    monkeypatch.setattr(
        cli_tools.run_ops,
        "solver_command",
        lambda *_a, **_k: ("simpleFoam", ["simpleFoam"]),
    )
    monkeypatch.setattr(cli_tools.run_ops, "dry_run_command", lambda _cmd: "simpleFoam")

    args = _ns(
        case_dir=Path("/case"),
        solver=None,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        receipt_file=None,
        record_inputs_copy=True,
        json=True,
    )
    assert cli_tools._knife_receipt_write(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["receipt"] == str(receipt_path)
    assert payload["recorded_inputs_copy"] is True

    monkeypatch.setattr(
        cli_tools.receipt_ops,
        "verify_run_receipt",
        lambda *_a, **_k: {
            "receipt": str(receipt_path),
            "case": "/case",
            "ok": False,
            "expected_tree_hash": "a",
            "actual_tree_hash": "b",
            "openfoam": {"match": True},
            "build": {
                "solver": {"match": False},
                "linked_libs": {"match": True},
            },
            "missing_files": [],
            "changed_files": [{"path": "system/controlDict"}],
            "extra_files": ["system/newDict"],
        },
    )
    assert cli_tools._knife_receipt_verify(_ns(receipt=receipt_path, case_dir=None, json=False)) == 1
    out = capsys.readouterr().out
    assert "changed_files:" in out
    assert "extra_files:" in out

    monkeypatch.setattr(
        cli_tools.receipt_ops,
        "restore_run_receipt",
        lambda *_a, **_k: {
            "receipt": str(receipt_path),
            "destination": str(restored_dir),
            "selected_roots": ["system", "constant"],
            "restored_receipt": str(restored_receipt),
            "restored": ["system", "constant", "0"],
            "ok": True,
        },
    )
    assert cli_tools._knife_receipt_restore(
        _ns(receipt=receipt_path, destination=restored_dir, only=["system"], skip=["0"], json=True),
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["destination"] == str(restored_dir)
    assert payload["selected_roots"] == ["system", "constant"]

    monkeypatch.setattr(cli_tools, "_parallel_setup_payload", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cli_tools.run_ops,
        "execute_solver_case_command",
        lambda *_a, **_k: cli_tools.run_ops.RunResult(
            0,
            "",
            "",
            pid=4321,
            log_path=Path("/case/log.simpleFoam"),
        ),
    )
    assert cli_tools._run_solver_execute(
        _ns(
            case_dir=Path("/case"),
            mpi=None,
            no_detach=False,
            log_file=None,
            pid_file=None,
            env=[],
            json=True,
            write_receipt=True,
            record_inputs_copy=False,
            receipt_file=None,
        ),
        background=True,
        display="simpleFoam",
        cmd=["simpleFoam"],
        parallel=0,
        sync_subdomains=True,
        clean_processors=False,
        prepare_parallel=True,
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["receipt_path"] == str(receipt_path)
    assert payload["write_receipt"] is True


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
        "external_watch_mode_payload",
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


def test_knife_stability_handler_plain_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.knife_ops,
        "stability_payload",
        lambda *_a, **_k: {
            "log": "log.simpleFoam",
            "pattern": "Cd",
            "count": 12,
            "window": 6,
            "tolerance": 0.01,
            "comparator": "le",
            "latest": 0.2,
            "window_delta": 0.005,
            "status": "pass",
            "unmet_reason": None,
            "eta_seconds": 0.0,
        },
    )
    args = _ns(
        source=Path("log.simpleFoam"),
        pattern="Cd",
        tolerance=0.01,
        window=6,
        startup_samples=0,
        comparator="le",
        json=False,
    )
    assert cli_tools._knife_stability(args) == 0
    assert "status=pass" in capsys.readouterr().out

    args.json = True
    assert cli_tools._knife_stability(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"


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


def test_knife_new_flag_forwarding_and_new_handlers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    compare_seen: dict[str, object] = {}
    status_seen: dict[str, object] = {}
    current_seen: dict[str, object] = {}

    def _compare(_left: Path, _right: Path, **kwargs: object) -> dict[str, object]:
        compare_seen.update(kwargs)
        return {
            "left_case": "left",
            "right_case": "right",
            "diff_count": 0,
            "diffs": [],
            "flat": kwargs.get("flat", False),
        }

    def _status(_case: Path, **kwargs: object) -> dict[str, object]:
        status_seen.update(kwargs)
        return {"case": "case"}

    def _current(_case: Path, **kwargs: object) -> dict[str, object]:
        current_seen.update(kwargs)
        return {
            "case": "case",
            "solver": "simpleFoam",
            "solver_error": None,
            "jobs": [],
            "jobs_total": 0,
            "jobs_running": 0,
            "jobs_tracked_running": 0,
            "untracked_processes": [],
        }

    monkeypatch.setattr(cli_tools.knife_ops, "compare_payload", _compare)
    monkeypatch.setattr(cli_tools.knife_ops, "status_payload", _status)
    monkeypatch.setattr(cli_tools.knife_ops, "current_payload", _current)
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")

    assert (
        cli_tools._knife_compare(
            _ns(
                left_case=Path("left"),
                right_case=Path("right"),
                flat=True,
                files=["system/controlDict,maxCoSchedule.dat"],
                raw_hash=True,
                json=False,
            ),
        )
        == 0
    )
    assert compare_seen["flat"] is True
    assert compare_seen["raw_hash_only"] is True
    assert compare_seen["files"] == ["system/controlDict,maxCoSchedule.dat"]
    capsys.readouterr()

    assert cli_tools._knife_status(_ns(case_dir=Path(), fast=True, easy_on_cpu=False, tail_bytes=4096, json=True)) == 0
    assert status_seen["lightweight"] is True
    assert status_seen["tail_bytes"] == 4096
    assert json.loads(capsys.readouterr().out)["case"] == "case"

    assert cli_tools._knife_current(_ns(case_dir=case, live=True, json=True)) == 0
    assert current_seen["live"] is True
    assert json.loads(capsys.readouterr().out)["solver"] == "simpleFoam"


def test_knife_current_scope_and_adopt_all_untracked_handlers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen_current: dict[str, object] = {}
    seen_adopt: dict[str, object] = {}

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "current_scope_payload",
        lambda case_dir, **kwargs: seen_current.update({"case_dir": case_dir, **kwargs}) or {
            "case": str(case_dir),
            "scope": "tree",
            "cases_total": 1,
            "cases": [str(case_dir)],
            "solver": None,
            "solver_error": None,
            "jobs": [],
            "jobs_total": 0,
            "jobs_running": 0,
            "jobs_tracked_running": 0,
            "jobs_registry_running": 0,
            "untracked_processes": [],
        },
    )
    assert cli_tools._knife_current(_ns(case_dir=Path("/x"), root=Path("/repo"), recursive=True, live=True, json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "tree"
    assert seen_current["recursive"] is True
    assert seen_current["live"] is True

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "adopt_payload",
        lambda case_dir, **kwargs: seen_adopt.update({"case_dir": case_dir, **kwargs}) or {
            "case": str(case_dir),
            "scope": "tree",
            "recursive": True,
            "all_untracked": True,
            "cases_total": 0,
            "cases": [],
            "selected": 0,
            "adopted": [],
            "failed": [],
            "skipped": [],
            "jobs_running_before": 0,
            "jobs_running_after": 0,
        },
    )
    assert cli_tools._knife_adopt(_ns(case_dir=Path("/x"), root=Path("/repo"), recursive=False, all_untracked=True, json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["all_untracked"] is True
    assert seen_adopt["all_untracked"] is True


def test_knife_criteria_eta_and_report_handlers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.knife_ops,
        "criteria_payload",
        lambda *_a, **_k: {
            "case": "case",
            "criteria_count": 1,
            "passed": 0,
            "failed": 1,
            "unknown": 0,
            "criteria": [
                {
                    "name": "residualTolerance",
                    "met": False,
                    "value": 0.1,
                    "tol": 0.01,
                    "unmet": "window",
                    "source": "runTimeControl",
                },
            ],
        },
    )
    assert cli_tools._knife_criteria(_ns(case_dir=Path(), fast=True, tail_bytes=1024, json=False)) == 0
    assert "residualTolerance" in capsys.readouterr().out

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "eta_payload",
        lambda *_a, **_k: {
            "case": "case",
            "mode": "criteria",
            "eta_seconds": 12.0,
            "eta_criteria_seconds": 12.0,
            "eta_end_time_seconds": 100.0,
        },
    )
    assert cli_tools._knife_eta(_ns(case_dir=Path(), mode="criteria", fast=False, tail_bytes=None, json=True)) == 0
    assert json.loads(capsys.readouterr().out)["eta_seconds"] == 12.0

    monkeypatch.setattr(cli_tools.knife_ops, "report_payload", lambda *_a, **_k: {"case": "case"})
    monkeypatch.setattr(cli_tools.knife_ops, "report_markdown", lambda _p: "# report")
    assert cli_tools._knife_report(_ns(case_dir=Path(), format="md", fast=False, tail_bytes=None, json=False)) == 0
    assert capsys.readouterr().out.strip() == "# report"
    assert cli_tools._knife_report(_ns(case_dir=Path(), format="json", fast=False, tail_bytes=None, json=True)) == 0
    assert json.loads(capsys.readouterr().out)["case"] == "case"


def test_watch_interval_output_and_adopt_handlers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "interval_payload",
        lambda *_a, **_k: {
            "case": "case",
            "effective": 0.5,
            "changed": True,
            "requested": 0.5,
            "settings_path": "/case/.ofti/watch.json",
        },
    )
    assert cli_tools._watch_interval(_ns(case_dir=Path(), seconds=0.5, json=False)) == 0
    assert "effective=0.5" in capsys.readouterr().out

    monkeypatch.setattr(
        cli_tools.watch_ops,
        "output_profile_payload",
        lambda *_a, **_k: {
            "case": "case",
            "effective": "brief",
            "changed": True,
            "requested": "brief",
            "settings_path": "/case/.ofti/watch.json",
        },
    )
    assert cli_tools._watch_output(_ns(case_dir=Path(), brief=True, detailed=False, json=False)) == 0
    assert "effective=brief" in capsys.readouterr().out
    assert cli_tools._watch_output(_ns(case_dir=Path(), brief=True, detailed=True, json=False)) == 2

    monkeypatch.setattr(
        cli_tools.watch_ops,
        "adopt_job_payload",
        lambda *_a, **_k: {
            "case": "case",
            "adopted": True,
            "job_id": "job-1",
            "pid": 123,
            "log": "/case/log.simpleFoam",
        },
    )
    captured: dict[str, object] = {}

    def _watch_log(args: argparse.Namespace) -> int:
        captured["job_id"] = args.job_id
        captured["follow"] = args.follow
        return 0

    monkeypatch.setattr(cli_tools, "_watch_log", _watch_log)
    assert (
        cli_tools._watch_attach(
            _ns(
                source=None,
                lines=40,
                job_id=None,
                adopt="123",
                case_dir=Path("/case"),
                output="brief",
                json=False,
            ),
        )
        == 0
    )
    assert captured["job_id"] == "job-1"
    assert captured["follow"] is True

    payload = cli_tools._watch_json_payload(
        "jobs",
        {"case": "/case", "count": 1, "jobs": [{"id": "j", "name": "w", "pid": 9, "status": "running"}]},
        profile="brief",
    )
    assert payload["schema"] == "ofti.watch.v1"
    assert payload["profile"] == "brief"


def test_watch_start_and_attach_watcher_modes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "watcher_start_payload",
        lambda *_a, **_k: {
            "case": "/case",
            "kind": "watcher",
            "name": "watcher",
            "command": ["python", "watcher.py"],
            "log_path": "/case/log.watcher",
            "pid": 123,
            "job_id": "w-1",
            "ok": True,
        },
    )
    args = _ns(
        case_dir=Path("/case"),
        solver=None,
        parallel=0,
        mpi=None,
        watcher=["python", "watcher.py"],
        watcher_name="watcher",
        no_detach=False,
        log_file=None,
        env=[],
        dry_run=False,
        json=False,
    )
    assert cli_tools._watch_start(args) == 0
    out = capsys.readouterr().out
    assert "kind=watcher" in out
    assert "job_id=w-1" in out

    monkeypatch.setattr(
        cli_tools.watch_ops,
        "watcher_attach_payload",
        lambda *_a, **_k: {
            "case": "/case",
            "kind": "watcher",
            "name": "watcher",
            "command": ["python", "watcher.py"],
            "pid": 321,
            "returncode": 0,
            "ok": True,
        },
    )
    attach_args = _ns(
        source=None,
        lines=40,
        job_id=None,
        watcher=["python", "watcher.py"],
        background=False,
        watcher_name="watcher",
        log_file=None,
        env=[],
        dry_run=False,
        adopt=None,
        case_dir=Path("/case"),
        output=None,
        json=True,
    )
    assert cli_tools._watch_attach(attach_args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "watcher"
    assert payload["pid"] == 321
