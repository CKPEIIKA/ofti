from __future__ import annotations

from pathlib import Path

from ofti.tools import runner_service
from ofti.tools.cli_tools import run


def _make_case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "0").mkdir()
    (path / "system" / "controlDict").write_text("application simpleFoam;\n")
    return path


def test_run_execute_wrapper_delegates_to_runner_service(tmp_path: Path, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    seen: dict[str, object] = {}

    def _execute(
        case_path: Path,
        name: str,
        cmd: list[str],
        *,
        background: bool,
        detached: bool = True,
        log_path: Path | None = None,
        pid_path: Path | None = None,
        extra_env: dict[str, str] | None = None,
        with_bashrc_fn,
        run_trusted_fn,
        popen_fn,
        register_job_fn,
    ) -> runner_service.RunResult:
        seen["case"] = case_path
        seen["name"] = name
        seen["cmd"] = cmd
        seen["background"] = background
        seen["detached"] = detached
        seen["log_path"] = log_path
        seen["pid_path"] = pid_path
        seen["extra_env"] = extra_env
        seen["with_bashrc_fn"] = with_bashrc_fn
        seen["run_trusted_fn"] = run_trusted_fn
        seen["popen_fn"] = popen_fn
        seen["register_job_fn"] = register_job_fn
        return runner_service.RunResult(0, "", "", pid=77, log_path=case_path / "log.simpleFoam")

    monkeypatch.setattr(runner_service, "execute_case_command", _execute)
    result = run.execute_case_command(
        case,
        "simpleFoam",
        ["simpleFoam"],
        background=True,
        detached=False,
        log_path=Path("log.x"),
        pid_path=Path("run.pid"),
        extra_env={"X": "1"},
    )
    assert result.pid == 77
    assert seen["case"] == case.resolve()
    assert seen["name"] == "simpleFoam"
    assert seen["cmd"] == ["simpleFoam"]
    assert seen["background"] is True
    assert seen["detached"] is False
    assert seen["log_path"] == Path("log.x")
    assert seen["pid_path"] == Path("run.pid")
    assert seen["extra_env"] == {"X": "1"}
    assert callable(seen["with_bashrc_fn"])
    assert callable(seen["run_trusted_fn"])
    assert callable(seen["popen_fn"])
    assert callable(seen["register_job_fn"])
