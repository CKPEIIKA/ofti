from __future__ import annotations

import json
from pathlib import Path

import pytest

from ofti.app import cli_tools
from ofti.tools import cli_tools_screens
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import watch as watch_ops
from ofti.tools.cli_tools.run import RunResult


def _make_case(path: Path, solver: str = "simpleFoam") -> Path:
    (path / "system").mkdir(parents=True)
    (path / "0").mkdir()
    (path / "system" / "controlDict").write_text(f"application {solver};\n")
    (path / "0" / "U").write_text("placeholder\n")
    (path / "0" / "p").write_text("placeholder\n")
    return path


def test_run_tool_list_outputs_catalog(tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")

    code = cli_tools.main(["run", "tool", "--case", str(case), "--list"])

    out = capsys.readouterr().out
    assert code == 0
    assert "blockMesh" in out


def test_cli_tools_without_args_prints_short_help(capsys) -> None:
    code = cli_tools.main([])
    out = capsys.readouterr().out
    assert code == 0
    assert "Non-interactive OFTI utilities" in out
    assert "{knife,plot,watch,run}" in out


def test_cli_group_without_subcommand_prints_help(capsys) -> None:
    code = cli_tools.main(["watch"])
    out = capsys.readouterr().out
    assert code == 0
    assert "usage: ofti watch" in out
    assert "{jobs,status,log,attach,start,pause,resume,interval,output,run,stop,external}" in out


def test_knife_group_help_lists_new_commands(capsys) -> None:
    code = cli_tools.main(["knife"])
    out = capsys.readouterr().out
    assert code == 0
    assert "criteria" in out
    assert "eta" in out
    assert "report" in out
    assert "campaign" in out


def test_run_tool_list_outputs_catalog_json(tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")

    code = cli_tools.main(["run", "tool", "--case", str(case), "--list", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["case"] == str(case.resolve())
    assert "blockMesh" in payload["tools"]


def test_run_tool_catalog_payload_matches_list_json(tmp_path) -> None:
    case = _make_case(tmp_path / "case")

    payload = cli_tools.run_ops.tool_catalog_payload(case)

    assert payload["case"] == str(case.resolve())
    assert "blockMesh" in payload["tools"]


def test_tui_run_export_tool_catalog_json_default_path(tmp_path, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    messages: list[str] = []

    monkeypatch.setattr(cli_tools_screens, "prompt_line", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(cli_tools_screens, "_show_message", lambda _screen, text: messages.append(text))

    cli_tools_screens._export_tool_catalog_json(object(), case)

    exported = case / ".ofti" / "tool_catalog.json"
    assert exported.is_file()
    payload = json.loads(exported.read_text())
    assert payload["case"] == str(case.resolve())
    assert "blockMesh" in payload["tools"]
    assert messages and "Exported" in messages[0]


def test_knife_preflight_reports_ok_for_minimal_case(tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")

    code = cli_tools.main(["knife", "preflight", str(case), "--json"])

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["checks"]["system/controlDict"] is True


def test_knife_initials_payload_json(tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")
    (case / "0" / "U").write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    class volVectorField;",
                "    object U;",
                "}",
                "internalField uniform (0 0 0);",
                "boundaryField",
                "{",
                "    inlet { type fixedValue; value uniform (1 0 0); }",
                "    outlet { type zeroGradient; }",
                "}",
            ],
        ),
    )
    code = cli_tools.main(["knife", "initials", str(case), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["field_count"] >= 1
    fields = {row["name"]: row for row in payload["fields"]}
    assert fields["U"]["internal_field"] in {"uniform (0 0 0)", "uniform (0.0 0.0 0.0)"}
    assert fields["U"]["boundary"]["inlet"]["type"] == "fixedValue"


def test_knife_copy_skips_runtime_artifacts(tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")
    (case / "1").mkdir()
    (case / "1" / "U").write_text("runtime\n")
    (case / "log.simpleFoam").write_text("log\n")
    (case / "postProcessing").mkdir()
    (case / "postProcessing" / "probe.dat").write_text("1\n")
    (case / "processor0").mkdir()
    (case / "processor0" / "U").write_text("runtime\n")
    (case / ".ofti").mkdir()
    (case / ".ofti" / "jobs.json").write_text("[]\n")
    (case / f"{case.name}.foam").write_text("\n")

    dest = tmp_path / "case_copy"
    code = cli_tools.main(
        ["knife", "copy", str(dest), "--case", str(case), "--json"],
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert dest.is_dir()
    assert (dest / "0" / "U").is_file()
    assert not (dest / "1").exists()
    assert not (dest / "log.simpleFoam").exists()
    assert not (dest / "postProcessing").exists()
    assert not (dest / "processor0").exists()
    assert not (dest / ".ofti").exists()
    assert not (dest / f"{case.name}.foam").exists()


def test_plot_metrics_reads_log_file(tmp_path, capsys) -> None:
    log_path = tmp_path / "log.simpleFoam"
    log_path.write_text(
        "\n".join(
            [
                "Time = 0.1",
                "Courant Number mean: 0.1 max: 0.7",
                "ExecutionTime = 1.0 s",
                "Time = 0.2",
                "Courant Number mean: 0.2 max: 0.8",
                "ExecutionTime = 1.7 s",
            ],
        ),
    )

    code = cli_tools.main(["plot", "metrics", str(log_path), "--json"])

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert payload["times"]["count"] == 2
    assert payload["courant"]["max"] == 0.8


def test_plot_metrics_without_logs_returns_error(tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")

    code = cli_tools.main(["plot", "metrics", str(case)])

    err = capsys.readouterr().err
    assert code == 1
    assert "no log.* files found" in err


def test_plot_criteria_alias_works(tmp_path, capsys) -> None:
    log_path = tmp_path / "log.simpleFoam"
    log_path.write_text("Time = 1\nCourant Number mean: 0.1 max: 0.2\nExecutionTime = 1.1 s\n")

    code = cli_tools.main(["plot", "criteria", str(log_path), "--json"])

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert payload["courant"]["max"] == 0.2


def test_watch_jobs_json_reports_running_job(tmp_path, capsys, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    jobs_file = case / ".ofti" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text(
        json.dumps(
            [
                {
                    "id": "123",
                    "name": "simpleFoam",
                    "pid": 99999,
                    "command": "simpleFoam",
                    "status": "running",
                    "started_at": 0.0,
                    "ended_at": None,
                    "returncode": None,
                    "log": str(case / "log.simpleFoam"),
                },
            ],
        ),
    )
    monkeypatch.setattr("ofti.tools.job_registry._pid_running", lambda _pid: True)

    code = cli_tools.main(["watch", "jobs", str(case), "--json"])

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert payload["count"] == 1
    assert payload["jobs"][0]["name"] == "simpleFoam"


def test_watch_jobs_brief_json_schema(tmp_path, capsys, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    jobs_file = case / ".ofti" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text(
        json.dumps(
            [
                {
                    "id": "123",
                    "name": "simpleFoam",
                    "pid": 99999,
                    "command": "simpleFoam",
                    "status": "running",
                    "started_at": 0.0,
                    "ended_at": None,
                    "returncode": None,
                    "log": str(case / "log.simpleFoam"),
                },
            ],
        ),
    )
    monkeypatch.setattr("ofti.tools.job_registry._pid_running", lambda _pid: True)

    code = cli_tools.main(["watch", "jobs", str(case), "--output", "brief", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == "ofti.watch.v1"
    assert payload["profile"] == "brief"
    assert payload["items"][0]["id"] == "123"


def test_knife_new_commands_json(tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")
    (case / "log.simpleFoam").write_text(
        "\n".join(
            [
                "Time = 0.1",
                "ExecutionTime = 1.0 s",
                "residualTolerance 0.2",
            ],
        ),
    )
    (case / "system" / "controlDict").write_text(
        "\n".join(
            [
                "application simpleFoam;",
                "startTime 0;",
                "endTime 1;",
                "residualTolerance 0.1;",
            ],
        ),
    )

    code = cli_tools.main(["knife", "criteria", str(case), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["criteria_count"] >= 1

    code = cli_tools.main(["knife", "eta", str(case), "--mode", "endtime", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["mode"] == "endtime"
    assert payload["eta_mode"] in {"end_time", "unavailable"}
    assert "eta_reason" in payload

    code = cli_tools.main(["knife", "report", str(case), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["case"] == str(case.resolve())


def test_knife_campaign_commands_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli_tools.knife_ops,
        "campaign_list_payload",
        lambda *_a, **_k: {"case": "/root", "count": 1, "cases": ["/root/caseA"]},
    )
    monkeypatch.setattr(
        cli_tools.knife_ops,
        "campaign_rank_payload",
        lambda *_a, **_k: {
            "case": "/root",
            "count": 1,
            "ranked": [{"case": "/root/caseA", "criteria_met": 1, "criteria_total": 1, "criteria_worst_ratio": 0.1}],
        },
    )
    monkeypatch.setattr(
        cli_tools.knife_ops,
        "campaign_stop_worst_payload",
        lambda *_a, **_k: {
            "case": "/root",
            "selected": 1,
            "dry_run": True,
            "targets": ["/root/caseA"],
            "actions": [],
        },
    )

    code = cli_tools.main(["knife", "campaign", "list", "/root", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["count"] == 1

    code = cli_tools.main(["knife", "campaign", "rank", "/root", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["count"] == 1

    code = cli_tools.main(["knife", "campaign", "stop", "/root", "--worst", "1", "--dry-run", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["dry_run"] is True


def test_watch_start_uses_watcher_preset_when_available(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_tools.watch_ops, "watcher_preset_payload", lambda _case: {"found": True})
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "watcher_start_payload",
        lambda *_a, **_k: {
            "case": "/case",
            "kind": "watcher",
            "name": "watcher",
            "command": ["python", "watcher.py"],
            "pid": 11,
            "job_id": "w-1",
            "ok": True,
        },
    )
    code = cli_tools.main(["watch", "start", "--case", "/case"])
    out = capsys.readouterr().out
    assert code == 0
    assert "kind=watcher" in out
    assert "job_id=w-1" in out


def test_watch_attach_watcher_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "watcher_attach_payload",
        lambda *_a, **_k: {
            "case": "/case",
            "kind": "watcher",
            "name": "watcher",
            "command": ["python", "watcher.py"],
            "pid": 12,
            "returncode": 0,
            "ok": True,
        },
    )
    code = cli_tools.main(
        [
            "watch",
            "attach",
            "--watcher",
            "python",
            "watcher.py",
            "--case",
            "/case",
            "--json",
        ],
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["kind"] == "watcher"
    assert payload["pid"] == 12


def test_watch_stop_stops_selected_job(tmp_path, capsys, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    jobs_file = case / ".ofti" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text(
        json.dumps(
            [
                {
                    "id": "job-1",
                    "name": "simpleFoam",
                    "pid": 4242,
                    "command": "simpleFoam",
                    "status": "running",
                    "started_at": 0.0,
                    "ended_at": None,
                    "returncode": None,
                    "log": str(case / "log.simpleFoam"),
                },
            ],
        ),
    )
    monkeypatch.setattr("ofti.tools.job_registry._pid_running", lambda _pid: True)
    monkeypatch.setattr("ofti.tools.watch_service.os.kill", lambda _pid, _sig: None)

    code = cli_tools.main(["watch", "stop", str(case), "--all", "--json"])

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert payload["selected"] == 1
    assert len(payload["stopped"]) == 1


def test_watch_start_runs_solver_in_background(tmp_path, capsys, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        "ofti.app.cli_tools.run_ops.solver_command",
        lambda _case, **_kwargs: ("simpleFoam", ["simpleFoam"]),
    )
    monkeypatch.setattr(
        "ofti.app.cli_tools.run_ops.execute_case_command",
        lambda _case, _name, _cmd, **_kwargs: RunResult(
            0,
            "",
            "",
            pid=1234,
            log_path=Path(_case) / "log.simpleFoam",
        ),
    )

    code = cli_tools.main(["watch", "start", str(case)])

    out = capsys.readouterr().out
    assert code == 0
    assert "pid=1234" in out


def test_knife_status_lightweight_flags_forwarded(monkeypatch, tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")
    seen: dict[str, object] = {}

    def _status(case_dir: Path, **kwargs: object) -> dict[str, object]:
        seen["case"] = case_dir
        seen.update(kwargs)
        return {
            "case": str(case_dir),
            "latest_time": 0.1,
            "latest_iteration": 1,
            "latest_delta_t": 1e-9,
            "sec_per_iter": 0.2,
            "solver_error": None,
            "solver": "simpleFoam",
            "solver_status": "running",
            "run_time_control": {
                "criteria": [
                    {
                        "key": "residualTolerance",
                        "status": "fail",
                        "live_value": 0.2,
                        "live_delta": 0.1,
                        "tolerance": 0.01,
                        "eta_seconds": None,
                        "unmet_reason": "window",
                    },
                ],
                "passed": 0,
                "failed": 1,
                "unknown": 0,
            },
            "eta_seconds_to_criteria_start": None,
            "eta_seconds_to_end_time": None,
            "log_path": str(case / "log.simpleFoam"),
            "log_fresh": False,
            "running": False,
            "tracked_solver_processes": [],
            "untracked_solver_processes": [],
            "jobs_running": 0,
            "jobs_total": 0,
        }

    monkeypatch.setattr(cli_tools.knife_ops, "status_payload", _status)
    code = cli_tools.main(
        [
            "knife",
            "status",
            str(case),
            "--lightweight",
            "--tail-bytes",
            "4096",
        ],
    )
    out = capsys.readouterr().out
    assert code == 0
    assert seen["lightweight"] is True
    assert seen["tail_bytes"] == 4096
    assert "unmet_reason=window" in out


def test_knife_status_defaults_to_fast_mode(monkeypatch, tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")
    seen: dict[str, object] = {}

    def _status(case_dir: Path, **kwargs: object) -> dict[str, object]:
        seen["case"] = case_dir
        seen.update(kwargs)
        return {"case": str(case_dir)}

    monkeypatch.setattr(cli_tools.knife_ops, "status_payload", _status)
    code = cli_tools.main(["knife", "status", str(case), "--json"])

    assert code == 0
    assert seen["lightweight"] is True
    assert json.loads(capsys.readouterr().out)["case"] == str(case)


def test_knife_status_full_disables_fast_mode(monkeypatch, tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")
    seen: dict[str, object] = {}

    def _status(case_dir: Path, **kwargs: object) -> dict[str, object]:
        seen["case"] = case_dir
        seen.update(kwargs)
        return {"case": str(case_dir)}

    monkeypatch.setattr(cli_tools.knife_ops, "status_payload", _status)
    code = cli_tools.main(["knife", "status", str(case), "--full", "--json"])

    assert code == 0
    assert seen["lightweight"] is False
    assert json.loads(capsys.readouterr().out)["case"] == str(case)


def test_knife_criteria_fast_default_with_full_override(monkeypatch, tmp_path, capsys) -> None:
    case = _make_case(tmp_path / "case")
    seen: list[dict[str, object]] = []

    def _criteria(case_dir: Path, **kwargs: object) -> dict[str, object]:
        seen.append({"case": case_dir, **kwargs})
        return {
            "case": str(case_dir),
            "criteria_count": 0,
            "passed": 0,
            "failed": 0,
            "unknown": 0,
            "criteria": [],
        }

    monkeypatch.setattr(cli_tools.knife_ops, "criteria_payload", _criteria)
    assert cli_tools.main(["knife", "criteria", str(case), "--json"]) == 0
    assert seen[0]["lightweight"] is True
    assert json.loads(capsys.readouterr().out)["case"] == str(case)

    assert cli_tools.main(["knife", "criteria", str(case), "--full", "--json"]) == 0
    assert seen[1]["lightweight"] is False
    assert json.loads(capsys.readouterr().out)["case"] == str(case)


def test_knife_set_uses_shared_logic(tmp_path, capsys, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        "ofti.app.cli_tools.knife_ops.set_entry_payload",
        lambda case_dir, rel_file, key, value: {
            "case": str(case_dir),
            "file": str(Path(case_dir) / rel_file),
            "key": key,
            "value": value,
            "ok": True,
        },
    )

    code = cli_tools.main(
        ["knife", "set", str(case), "system/controlDict", "application", "simpleFoam;"],
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "ok=True" in out


def test_run_solver_dry_run_uses_control_dict_solver(tmp_path, capsys, monkeypatch) -> None:
    case = _make_case(tmp_path / "case", solver="rhoSimpleFoam")
    monkeypatch.setattr(
        "ofti.app.cli_tools.run_ops.solver_command",
        lambda _case, **_kwargs: ("rhoSimpleFoam", ["rhoSimpleFoam"]),
    )

    code = cli_tools.main(["run", "solver", str(case), "--dry-run"])

    out = capsys.readouterr().out
    assert code == 0
    assert "rhoSimpleFoam" in out


def test_run_solver_dry_run_json(tmp_path, capsys, monkeypatch) -> None:
    case = _make_case(tmp_path / "case", solver="rhoSimpleFoam")
    monkeypatch.setattr(
        "ofti.app.cli_tools.run_ops.solver_command",
        lambda _case, **_kwargs: ("rhoSimpleFoam", ["rhoSimpleFoam"]),
    )

    code = cli_tools.main(["run", "solver", str(case), "--dry-run", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["dry_run"] is True
    assert "rhoSimpleFoam" in payload["command"]


def test_watch_attach_forwards_job_id_to_log_handler(tmp_path, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    captured: dict[str, object] = {}

    def fake_watch_log(args):
        captured["job_id"] = args.job_id
        captured["case_dir"] = args.case_dir
        captured["follow"] = args.follow
        return 0

    monkeypatch.setattr("ofti.app.cli_tools._watch_log", fake_watch_log)

    code = cli_tools.main(["watch", "attach", "--job-id", "job-1", "--case", str(case)])

    assert code == 0
    assert captured["job_id"] == "job-1"
    assert captured["follow"] is True
    assert Path(str(captured["case_dir"])) == case


def test_watch_log_payload_for_job_id_reads_registered_log(tmp_path) -> None:
    case = _make_case(tmp_path / "case")
    log_path = case / "log.simpleFoam"
    log_path.write_text("line-a\nline-b\nline-c\n")
    jobs_file = case / ".ofti" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text(
        json.dumps(
            [
                {
                    "id": "job-1",
                    "name": "simpleFoam",
                    "pid": 1,
                    "command": "simpleFoam",
                    "status": "finished",
                    "started_at": 0.0,
                    "ended_at": 1.0,
                    "returncode": 0,
                    "log": str(log_path),
                },
            ],
        ),
    )

    payload = watch_ops.log_tail_payload_for_job(case, job_id="job-1", lines=2)

    assert payload["log"] == str(log_path.resolve())
    assert payload["lines"] == ["line-b", "line-c"]


def test_watch_log_json(tmp_path, capsys) -> None:
    log_path = tmp_path / "log.simpleFoam"
    log_path.write_text("line1\nline2\nline3\n")

    code = cli_tools.main(["watch", "log", str(log_path), "--lines", "2", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["lines"] == ["line2", "line3"]


def test_watch_log_json_rejects_follow(tmp_path, capsys) -> None:
    log_path = tmp_path / "log.simpleFoam"
    log_path.write_text("line1\n")

    code = cli_tools.main(["watch", "log", str(log_path), "--follow", "--json"])

    err = capsys.readouterr().err
    assert code == 2
    assert "--json cannot be used with --follow" in err


def test_knife_current_includes_untracked_solver_processes(tmp_path, monkeypatch) -> None:
    case = _make_case(tmp_path / "case", solver="hy2Foam")
    monkeypatch.setattr(
        "ofti.tools.knife_service.resolve_solver_name",
        lambda _case: ("hy2Foam", None),
    )
    monkeypatch.setattr(
        "ofti.tools.knife_service.refresh_jobs",
        lambda _case: [{"id": "job-1", "name": "hy2Foam", "pid": 123, "status": "running"}],
    )
    monkeypatch.setattr(
        "ofti.tools.knife_service._scan_proc_solver_processes",
        lambda _case, _solver, **_kwargs: [
            {"pid": 777, "solver": "hy2Foam", "command": "hy2Foam -case /tmp/case"},
        ],
    )

    payload = knife_ops.current_payload(case)

    assert payload["jobs_running"] == 1
    assert payload["untracked_processes"][0]["pid"] == 777


def test_knife_set_json_output(tmp_path, capsys, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        "ofti.app.cli_tools.knife_ops.set_entry_payload",
        lambda case_dir, rel_file, key, value: {
            "case": str(case_dir),
            "file": str(Path(case_dir) / rel_file),
            "key": key,
            "value": value,
            "ok": True,
        },
    )

    code = cli_tools.main(
        ["knife", "set", str(case), "system/controlDict", "application", "simpleFoam;", "--json"],
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True


def test_run_tool_help_mentions_presets(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli_tools.build_parser().parse_args(["run", "tool", "--help"])
    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "--json" in out


def test_knife_converge_cli_json(tmp_path, capsys, monkeypatch) -> None:
    log_path = tmp_path / "log.hy2Foam"
    log_path.write_text("Time = 1\n")
    monkeypatch.setattr(
        "ofti.app.cli_tools.knife_ops.converge_payload",
        lambda *_args, **_kwargs: {
            "log": str(log_path),
            "shock": {"drift": 0.1, "limit": 0.02, "ok": False},
            "drag": {"band": 0.01, "limit": 0.02, "ok": True},
            "mass": {"last_abs_global": 1e-5, "limit": 1e-4, "ok": True},
            "residuals": {"flatline": False, "flatline_fields": []},
            "thermo": {"out_of_range_count": 0, "ok": True},
            "strict": True,
            "strict_ok": False,
            "ok": False,
        },
    )

    code = cli_tools.main(["knife", "converge", str(log_path), "--strict", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["strict_ok"] is False


def test_watch_external_cli_dry_run_json(tmp_path, capsys, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        "ofti.app.cli_tools.watch_ops.external_watch_payload",
        lambda *_args, **_kwargs: {
            "case": str(case),
            "command": ["python", "watcher.py"],
            "dry_run": True,
            "ok": True,
        },
    )

    code = cli_tools.main(
        [
            "watch",
            "external",
            "--case",
            str(case),
            "--dry-run",
            "--json",
            "--",
            "python",
            "watcher.py",
        ],
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["dry_run"] is True


def test_watch_pause_resume_and_stop_signal_cli(tmp_path, capsys, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        "ofti.app.cli_tools.watch_ops.pause_payload",
        lambda *_args, **_kwargs: {
            "case": str(case),
            "selected": 1,
            "paused": [{"id": "job-1", "pid": 123, "name": "simpleFoam"}],
            "failed": [],
        },
    )
    code = cli_tools.main(["watch", "pause", str(case), "--json"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["selected"] == 1

    monkeypatch.setattr(
        "ofti.app.cli_tools.watch_ops.resume_payload",
        lambda *_args, **_kwargs: {
            "case": str(case),
            "selected": 1,
            "resumed": [{"id": "job-1", "pid": 123, "name": "simpleFoam"}],
            "failed": [],
        },
    )
    code = cli_tools.main(["watch", "resume", str(case)])
    assert code == 0
    assert "resumed:" in capsys.readouterr().out

    monkeypatch.setattr(
        "ofti.app.cli_tools.watch_ops.stop_payload",
        lambda *_args, **kwargs: {
            "case": str(case),
            "signal": kwargs.get("signal_name", "TERM"),
            "selected": 1,
            "stopped": [{"id": "job-1", "pid": 123, "name": "simpleFoam"}],
            "failed": [],
        },
    )
    code = cli_tools.main(["watch", "stop", str(case), "--signal", "INT"])
    assert code == 0
    assert "signal=INT" in capsys.readouterr().out
