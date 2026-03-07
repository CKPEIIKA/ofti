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
    monkeypatch.setattr("ofti.tools.cli_tools.watch.os.kill", lambda _pid, _sig: None)

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
        "ofti.tools.cli_tools.knife.resolve_solver_name",
        lambda _case: ("hy2Foam", None),
    )
    monkeypatch.setattr(
        "ofti.tools.cli_tools.knife.refresh_jobs",
        lambda _case: [{"id": "job-1", "name": "hy2Foam", "pid": 123, "status": "running"}],
    )
    monkeypatch.setattr(
        "ofti.tools.cli_tools.knife._scan_proc_solver_processes",
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
