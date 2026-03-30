from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from ofti.app import cli_tools
from ofti.tools.cli_tools.run import RunResult


def _ns(**kwargs: object) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_main_catches_value_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class FakeParser:
        def parse_args(self, _argv: list[str] | None) -> argparse.Namespace:
            return _ns(func=lambda _args: (_ for _ in ()).throw(ValueError("bad args")))

    def _build_parser() -> FakeParser:
        return FakeParser()

    monkeypatch.setattr(cli_tools, "build_parser", _build_parser)
    code = cli_tools.main(["knife", "status"])
    assert code == 2
    assert "ofti: bad args" in capsys.readouterr().err


def test_knife_doctor_plain_formats_errors_and_warnings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.knife_ops,
        "doctor_payload",
        lambda _case: {
            "case": "case-path",
            "lines": ["line-1"],
            "errors": ["broken"],
            "warnings": ["warn"],
        },
    )
    monkeypatch.setattr(cli_tools.knife_ops, "doctor_exit_code", lambda payload: 1 if payload["errors"] else 0)
    code = cli_tools._knife_doctor(_ns(case_dir=Path(), json=False))
    out = capsys.readouterr().out
    assert code == 1
    assert "Errors:" in out
    assert "Warnings:" in out


def test_knife_compare_plain_no_diffs_and_with_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.knife_ops,
        "compare_payload",
        lambda _left, _right: {
            "left_case": "a",
            "right_case": "b",
            "diff_count": 0,
            "diffs": [],
        },
    )
    code = cli_tools._knife_compare(_ns(left_case=Path("a"), right_case=Path("b"), json=False))
    assert code == 0
    assert "No dictionary key differences detected." in capsys.readouterr().out

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "compare_payload",
        lambda _left, _right: {
            "left_case": "a",
            "right_case": "b",
            "diff_count": 1,
            "diffs": [
                {
                    "rel_path": "system/controlDict",
                    "missing_in_left": [],
                    "missing_in_right": [],
                    "error": "parse failed",
                },
            ],
        },
    )
    code = cli_tools._knife_compare(_ns(left_case=Path("a"), right_case=Path("b"), json=False))
    assert code == 0
    assert "error: parse failed" in capsys.readouterr().out


def test_knife_preflight_status_current_and_set_plain(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.knife_ops,
        "preflight_payload",
        lambda _case: {
            "case": "case-path",
            "checks": {"system/controlDict": True, "solver_entry": True},
            "solver_error": None,
            "ok": True,
        },
    )
    assert cli_tools._knife_preflight(_ns(case_dir=Path(), json=False)) == 0
    assert "system/controlDict=ok" in capsys.readouterr().out

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "status_payload",
        lambda _case: {
            "case": "case-path",
            "latest_time": "10",
            "solver_error": None,
            "solver": "simpleFoam",
            "solver_status": None,
            "jobs_running": 0,
            "jobs_total": 1,
        },
    )
    assert cli_tools._knife_status(_ns(case_dir=Path(), json=False)) == 0
    assert "solver_status=not tracked" in capsys.readouterr().out

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "current_payload",
        lambda _case: {
            "case": "case-path",
            "solver_error": None,
            "solver": "simpleFoam",
            "jobs": [{"name": "simpleFoam", "pid": 99, "status": "running"}],
            "untracked_processes": [{"pid": 88, "solver": "simpleFoam", "command": "simpleFoam -case ."}],
        },
    )
    assert cli_tools._knife_current(_ns(case_dir=Path(), json=False)) == 0
    out = capsys.readouterr().out
    assert "tracked_jobs:" in out
    assert "untracked_solver_processes:" in out

    monkeypatch.setattr(
        cli_tools.knife_ops,
        "set_entry_payload",
        lambda *_args, **_kwargs: {"file": "f", "key": "k", "value": "v", "ok": False},
    )
    assert cli_tools._knife_set(_ns(case_dir=Path(), file="f", key="k", value=["v"], json=False)) == 1
    assert "ok=False" in capsys.readouterr().out


def test_plot_handlers_error_and_empty_residuals(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_tools.plot_ops, "metrics_payload", lambda _source: (_ for _ in ()).throw(ValueError("bad log")))
    code = cli_tools._plot_metrics(_ns(source=Path(), json=False))
    assert code == 1
    assert "ofti: bad log" in capsys.readouterr().err

    monkeypatch.setattr(
        cli_tools.plot_ops,
        "residuals_payload",
        lambda _source, **_kwargs: {"log": "case-log", "fields": []},
    )
    code = cli_tools._plot_residuals(_ns(source=Path(), field=[], limit=0, json=False))
    assert code == 1
    assert "No residuals found in case-log" in capsys.readouterr().err


def test_plot_handlers_success_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.plot_ops,
        "metrics_payload",
        lambda _source: {
            "log": "log.simpleFoam",
            "times": {"count": 2, "last": 0.2},
            "courant": {"count": 2, "max": 0.8},
            "execution_time": {"count": 2, "last": 1.2, "delta_min": 0.4, "delta_avg": 0.5, "delta_max": 0.6},
            "residual_fields": ["U", "p"],
        },
    )
    assert cli_tools._plot_metrics(_ns(source=Path(), json=False)) == 0
    out = capsys.readouterr().out
    assert "step_time=min:0.4 avg:0.5 max:0.6" in out
    assert "residual_fields=U,p" in out

    monkeypatch.setattr(
        cli_tools.plot_ops,
        "residuals_payload",
        lambda _source, **_kwargs: {
            "log": "log.simpleFoam",
            "fields": [{"field": "U", "count": 3, "last": 1.0, "min": 0.1, "max": 2.0}],
        },
    )
    assert cli_tools._plot_residuals(_ns(source=Path(), field=[], limit=0, json=True)) == 0
    assert json.loads(capsys.readouterr().out)["fields"][0]["field"] == "U"

    monkeypatch.setattr(cli_tools.plot_ops, "residuals_payload", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad residuals")))
    assert cli_tools._plot_residuals(_ns(source=Path(), field=[], limit=0, json=False)) == 1
    assert "ofti: bad residuals" in capsys.readouterr().err


def test_watch_jobs_plain_and_watch_attach_forwarding(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "jobs_payload",
        lambda _case, **_kwargs: {"case": "case-path", "count": 0, "jobs": []},
    )
    code = cli_tools._watch_jobs(_ns(case_dir=Path(), all=False, json=False))
    assert code == 0
    assert "No tracked jobs." in capsys.readouterr().out

    captured: dict[str, object] = {}

    def fake_watch_log(args: argparse.Namespace) -> int:
        captured["source"] = args.source
        captured["follow"] = args.follow
        captured["easy_on_cpu"] = args.easy_on_cpu
        return 7

    monkeypatch.setattr(cli_tools, "_watch_log", fake_watch_log)
    case_dir = Path("relative-case")
    code = cli_tools._watch_attach(
        _ns(source=None, lines=10, job_id="j1", case_dir=case_dir, easy_on_cpu=True, json=False),
    )
    assert code == 7
    assert captured["source"] == case_dir
    assert captured["follow"] is True
    assert captured["easy_on_cpu"] is True


def test_watch_jobs_with_rows(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "jobs_payload",
        lambda _case, **_kwargs: {
            "case": "case-path",
            "count": 1,
            "jobs": [{"name": "simpleFoam", "pid": 123, "status": "running"}],
        },
    )
    assert cli_tools._watch_jobs(_ns(case_dir=Path(), all=False, json=False)) == 0
    out = capsys.readouterr().out
    assert "simpleFoam kind=unknown pid=123 status=running" in out


def test_watch_log_follow_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log_path = tmp_path / "log.simpleFoam"
    log_path.write_text("line-1\n")
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "log_tail_payload",
        lambda _source, **_kwargs: {"log": str(log_path), "lines": []},
    )
    monkeypatch.setattr(cli_tools.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    args = _ns(source=tmp_path, case_dir=tmp_path, lines=5, follow=True, job_id=None, json=False)
    assert cli_tools._watch_log(args) == 0

    missing = tmp_path / "missing.log"
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "log_tail_payload",
        lambda _source, **_kwargs: {"log": str(missing), "lines": []},
    )
    assert cli_tools._watch_log(args) == 1
    assert "Failed to follow" in capsys.readouterr().err


def test_watch_log_job_id_and_value_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log_path = tmp_path / "log.simpleFoam"
    log_path.write_text("line-1\nline-2\n")
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "log_tail_payload_for_job",
        lambda _case, **_kwargs: {"log": str(log_path), "lines": ["line-2"]},
    )
    args = _ns(source=tmp_path, case_dir=tmp_path, lines=5, follow=False, job_id="job-1", json=False)
    assert cli_tools._watch_log(args) == 0
    assert "line-2" in capsys.readouterr().out

    monkeypatch.setattr(
        cli_tools.watch_ops,
        "log_tail_payload",
        lambda _source, **_kwargs: (_ for _ in ()).throw(ValueError("bad log")),
    )
    args = _ns(source=tmp_path, case_dir=tmp_path, lines=5, follow=False, job_id=None, json=False)
    assert cli_tools._watch_log(args) == 1
    assert "ofti: bad log" in capsys.readouterr().err


def test_watch_log_follow_prints_new_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log_path = tmp_path / "log.simpleFoam"
    log_path.write_text("")
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "log_tail_payload",
        lambda _source, **_kwargs: {"log": str(log_path), "lines": []},
    )

    class _Handle:
        def __init__(self) -> None:
            self._read_count = 0

        def __enter__(self) -> _Handle:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def seek(self, *_args: object) -> None:
            return None

        def readline(self) -> str:
            self._read_count += 1
            return "new-line\n" if self._read_count == 1 else ""

    monkeypatch.setattr(Path, "open", lambda *_a, **_k: _Handle())
    monkeypatch.setattr(cli_tools.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()))
    args = _ns(source=tmp_path, case_dir=tmp_path, lines=5, follow=True, job_id=None, json=False)
    assert cli_tools._watch_log(args) == 0
    assert "new-line" in capsys.readouterr().out


def test_watch_log_easy_on_cpu_enforces_min_follow_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "log.simpleFoam"
    log_path.write_text("")
    seen: dict[str, float] = {}
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "log_tail_payload",
        lambda _source, **_kwargs: {"log": str(log_path), "lines": []},
    )
    monkeypatch.setattr(cli_tools.watch_ops, "effective_interval", lambda _case_dir: 0.1)

    def _follow(_path: Path, *, interval: float) -> int:
        seen["interval"] = interval
        return 0

    monkeypatch.setattr(cli_tools, "_follow_log_path", _follow)
    args = _ns(source=tmp_path, case_dir=tmp_path, lines=5, follow=True, job_id=None, easy_on_cpu=True, json=False)
    assert cli_tools._watch_log(args) == 0
    assert seen["interval"] == pytest.approx(1.0)


def test_watch_stop_plain_failed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        cli_tools.watch_ops,
        "stop_payload",
        lambda *_args, **_kwargs: {
            "case": "case-path",
            "selected": 2,
            "stopped": [{"id": "1", "pid": 100, "name": "simpleFoam"}],
            "failed": [{"id": "2", "pid": 200, "error": "gone"}],
        },
    )
    code = cli_tools._watch_stop(_ns(case_dir=Path(), job_id=None, name=None, all=False, json=False))
    out = capsys.readouterr().out
    assert code == 1
    assert "stopped:" in out
    assert "failed:" in out


def test_run_tool_branches(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(ValueError, match="tool name is required"):
        cli_tools._run_tool(_ns(list=False, json=False, name=None, case_dir=Path(), background=False))

    monkeypatch.setattr(cli_tools.run_ops, "resolve_tool", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli_tools.run_ops, "tool_catalog_names", lambda _case: ["blockMesh"])
    code = cli_tools._run_tool(_ns(list=False, json=False, name="missing", case_dir=Path(), background=False))
    assert code == 1
    err = capsys.readouterr().err
    assert "Unknown tool: missing" in err
    assert "Available tools: blockMesh" in err

    code = cli_tools._run_tool(_ns(list=False, json=True, name="missing", case_dir=Path(), background=False))
    assert code == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == "unknown tool"


def test_run_tool_outputs_json_and_background_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(cli_tools.run_ops, "resolve_tool", lambda *_args, **_kwargs: ("blockMesh", ["blockMesh"]))
    monkeypatch.setattr(cli_tools.run_ops, "dry_run_command", lambda _cmd: "blockMesh")

    monkeypatch.setattr(
        cli_tools.run_ops,
        "execute_case_command",
        lambda *_args, **_kwargs: RunResult(0, "", "", pid=321, log_path=case / "log.blockMesh"),
    )
    code = cli_tools._run_tool(_ns(list=False, json=True, name="blockMesh", case_dir=case, background=True))
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["pid"] == 321

    monkeypatch.setattr(
        cli_tools.run_ops,
        "execute_case_command",
        lambda *_args, **_kwargs: RunResult(0, "done\n", "warn\n", pid=None, log_path=None),
    )
    code = cli_tools._run_tool(_ns(list=False, json=False, name="blockMesh", case_dir=case, background=False))
    out = capsys.readouterr()
    assert code == 0
    assert "done" in out.out
    assert "warn" in out.err


def test_run_tool_background_plain_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(cli_tools.run_ops, "resolve_tool", lambda *_args, **_kwargs: ("blockMesh", ["blockMesh"]))
    monkeypatch.setattr(
        cli_tools.run_ops,
        "execute_case_command",
        lambda *_args, **_kwargs: RunResult(0, "", "", pid=55, log_path=case / "log.blockMesh"),
    )
    assert cli_tools._run_tool(_ns(list=False, json=False, name="blockMesh", case_dir=case, background=True)) == 0
    assert "Started blockMesh in background: pid=55" in capsys.readouterr().out


def test_run_solver_with_mode_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(cli_tools.run_ops, "solver_command", lambda *_args, **_kwargs: ("simpleFoam", ["simpleFoam"]))
    monkeypatch.setattr(cli_tools.run_ops, "dry_run_command", lambda _cmd: "simpleFoam")

    args = _ns(case_dir=case, solver=None, parallel=0, mpi=None, dry_run=True, json=False)
    assert cli_tools._run_solver_with_mode(args, background=False) == 0
    assert "simpleFoam" in capsys.readouterr().out

    args = _ns(case_dir=case, solver=None, parallel=0, mpi=None, dry_run=True, json=True)
    assert cli_tools._run_solver_with_mode(args, background=False) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True

    monkeypatch.setattr(
        cli_tools.run_ops,
        "execute_solver_case_command",
        lambda *_args, **_kwargs: RunResult(0, "", "", pid=777, log_path=case / "log.simpleFoam"),
    )
    args = _ns(case_dir=case, solver=None, parallel=0, mpi=None, json=False, dry_run=False)
    assert cli_tools._run_solver_with_mode(args, background=True) == 0
    assert "pid=777" in capsys.readouterr().out

    monkeypatch.setattr(
        cli_tools.run_ops,
        "execute_solver_case_command",
        lambda *_args, **_kwargs: RunResult(1, "stdout\n", "stderr\n", pid=None, log_path=None),
    )
    args = _ns(case_dir=case, solver=None, parallel=0, mpi=None, json=False, dry_run=False)
    assert cli_tools._run_solver_with_mode(args, background=False) == 1
    out = capsys.readouterr()
    assert "stdout" in out.out
    assert "stderr" in out.err


def test_watch_run_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_tools, "_run_solver_with_mode", lambda _args, **_kwargs: 9)
    assert cli_tools._watch_run(_ns()) == 9


def test_run_solver_with_mode_json_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(cli_tools.run_ops, "solver_command", lambda *_args, **_kwargs: ("simpleFoam", ["simpleFoam"]))
    monkeypatch.setattr(cli_tools.run_ops, "dry_run_command", lambda _cmd: "simpleFoam")
    monkeypatch.setattr(
        cli_tools.run_ops,
        "execute_solver_case_command",
        lambda *_args, **_kwargs: RunResult(0, "ok", "", pid=None, log_path=None),
    )
    args = _ns(case_dir=case, solver=None, parallel=0, mpi=None, json=True, dry_run=False)
    assert cli_tools._run_solver_with_mode(args, background=False) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False


def test_run_solver_with_mode_forwards_sync_subdomains_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    seen: dict[str, object] = {}

    def _solver_command(*_args: object, **kwargs: object) -> tuple[str, list[str]]:
        seen["sync_subdomains"] = kwargs.get("sync_subdomains")
        return ("simpleFoam", ["simpleFoam"])

    monkeypatch.setattr(cli_tools.run_ops, "solver_command", _solver_command)
    monkeypatch.setattr(
        cli_tools.run_ops,
        "execute_solver_case_command",
        lambda *_args, **_kwargs: RunResult(0, "ok", "", pid=None, log_path=None),
    )
    args = _ns(
        case_dir=case,
        solver=None,
        parallel=2,
        mpi="mpirun",
        sync_subdomains=False,
        json=False,
        dry_run=False,
    )
    assert cli_tools._run_solver_with_mode(args, background=False) == 0
    assert seen["sync_subdomains"] is False


def test_knife_converge_plain_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_tools.knife_ops,
        "converge_payload",
        lambda *_args, **_kwargs: {
            "log": "log.hy2Foam",
            "shock": {"drift": 0.01, "limit": 0.02, "ok": True},
            "drag": {"band": 0.01, "limit": 0.02, "ok": True},
            "mass": {"last_abs_global": 1e-5, "limit": 1e-4, "ok": True},
            "residuals": {"flatline": False, "flatline_fields": []},
            "thermo": {"out_of_range_count": 0, "ok": True},
            "strict": True,
            "strict_ok": True,
            "ok": True,
        },
    )
    args = _ns(
        source=Path("log.hy2Foam"),
        strict=True,
        shock_drift_limit=0.02,
        drag_band_limit=0.02,
        mass_limit=1e-4,
        json=False,
    )
    assert cli_tools._knife_converge(args) == 0
    assert "strict_ok=True" in capsys.readouterr().out

    args.json = True
    assert cli_tools._knife_converge(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_watch_external_handler_requires_command_and_formats_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _ns(
        case_dir=Path("case"),
        command=[],
        dry_run=False,
        json=False,
    )
    assert cli_tools._watch_external(args) == 2
    assert "external command is required" in capsys.readouterr().err

    monkeypatch.setattr(
        cli_tools.watch_ops,
        "external_watch_mode_payload",
        lambda *_a, **_k: {
            "case": "/case",
            "command": ["python", "watcher.py"],
            "pid": 555,
            "returncode": 0,
            "ok": True,
        },
    )
    args.command = ["python", "watcher.py"]
    assert cli_tools._watch_external(args) == 0
    out = capsys.readouterr().out
    assert "pid=555" in out
    assert "returncode=0" in out


def test_watch_external_handler_start_status_attach_stop_modes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _payload(*_a: object, **kwargs: object) -> dict[str, object]:
        mode = str(kwargs.get("mode"))
        if mode == "start":
            return {
                "case": "/case",
                "name": "watch.external",
                "command": ["python", "watcher.py"],
                "log_path": "/case/log.watch.external",
                "dry_run": False,
                "pid": 123,
                "job_id": "job-1",
                "ok": True,
            }
        if mode == "status":
            return {
                "case": "/case",
                "name": "watch.external",
                "count": 1,
                "jobs": [{"id": "job-1", "name": "watch.external", "pid": 1, "status": "running"}],
            }
        if mode == "attach":
            return {
                "case": "/case",
                "log": "/case/log.watch.external",
                "lines": ["a", "b"],
                "job_id": "job-1",
                "name": "watch.external",
            }
        return {
            "case": "/case",
            "name": "watch.external",
            "signal": "TERM",
            "selected": 1,
            "stopped": [{"id": "job-1", "pid": 1, "name": "watch.external"}],
            "failed": [],
        }

    monkeypatch.setattr(cli_tools.watch_ops, "external_watch_mode_payload", _payload)
    args = _ns(
        case_dir=Path("/case"),
        command=["python", "watcher.py"],
        start=True,
        status=False,
        attach=False,
        stop=False,
        job_id=None,
        name="watch.external",
        all=False,
        lines=10,
        follow=False,
        interval=0.25,
        log_file=None,
        no_detach=False,
        signal="TERM",
        dry_run=False,
        json=False,
    )
    assert cli_tools._watch_external(args) == 0
    assert "job_id=job-1" in capsys.readouterr().out

    args.start = False
    args.status = True
    assert cli_tools._watch_external(args) == 0
    assert "count=1" in capsys.readouterr().out

    args.status = False
    args.attach = True
    assert cli_tools._watch_external(args) == 0
    assert "a\nb" in capsys.readouterr().out

    args.attach = False
    args.stop = True
    assert cli_tools._watch_external(args) == 0
    assert "selected=1" in capsys.readouterr().out


def test_watch_external_attach_easy_on_cpu_enforces_min_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, float] = {}

    def _follow(_path: Path, *, interval: float) -> int:
        seen["interval"] = interval
        return 0

    monkeypatch.setattr(cli_tools, "_follow_log_path", _follow)
    args = _ns(case_dir=Path("/case"), output=None, follow=True, interval=0.25, easy_on_cpu=True)
    payload = {"log": "/case/log.watch.external", "lines": []}
    assert cli_tools._print_watch_external_attach(args, payload) == 0
    assert seen["interval"] == pytest.approx(1.0)
