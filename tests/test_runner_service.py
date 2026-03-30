from __future__ import annotations

from pathlib import Path
from typing import cast

from ofti.tools import runner_service as svc


def test_runner_service_foreground_env_and_output(tmp_path: Path, monkeypatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    seen: dict[str, object] = {}
    monkeypatch.setenv("BASH_ENV", "x")
    monkeypatch.setenv("ENV", "y")

    class _Result:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "ok\n"
            self.stderr = ""

    def _run_trusted(argv: list[str], **kwargs: object) -> _Result:
        seen["argv"] = argv
        seen.update(kwargs)
        return _Result()

    result = svc.execute_case_command(
        case,
        "simpleFoam",
        ["simpleFoam"],
        background=False,
        with_bashrc_fn=lambda cmd: cmd,
        run_trusted_fn=_run_trusted,
        popen_fn=lambda *_a, **_k: None,
        register_job_fn=lambda *_a, **_k: None,
    )

    assert result.returncode == 0
    assert result.stdout == "ok\n"
    env = seen["env"]
    assert isinstance(env, dict)
    assert "BASH_ENV" not in env
    assert "ENV" not in env


def test_runner_service_background_detached_and_files(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    captured: dict[str, object] = {}
    registered: list[tuple[str, int, Path]] = []

    class _PopenResult:
        def __init__(self) -> None:
            self.pid = 4242

    class _RunTrustedResult:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    def _popen(argv: list[str], **kwargs: object) -> _PopenResult:
        captured["argv"] = argv
        captured.update(kwargs)
        return _PopenResult()

    def _register(
        case_path: Path,
        name: str,
        pid: int,
        _shell_cmd: str,
        log_path: Path | None,
    ) -> None:
        assert log_path is not None
        registered.append((name, pid, log_path))
        assert case_path == case

    pid_file = case / ".ofti" / "pid.txt"
    result = svc.execute_case_command(
        case,
        "tool with spaces!",
        ["echo", "hi"],
        background=True,
        detached=True,
        pid_path=pid_file,
        extra_env={"X": "1"},
        with_bashrc_fn=lambda cmd: cmd,
        run_trusted_fn=lambda *_a, **_k: _RunTrustedResult(),
        popen_fn=_popen,
        register_job_fn=_register,
    )

    assert result.pid == 4242
    assert result.log_path is not None
    assert result.log_path.name == "log.toolwithspaces"
    assert registered and registered[0][0] == "tool with spaces!"
    assert captured["start_new_session"] is True
    env = captured["env"]
    env_map = cast("dict[str, str]", env)
    assert env_map.get("X") == "1"
    assert pid_file.read_text().strip() == "4242"
    stdout_handle = captured["stdout"]
    assert hasattr(stdout_handle, "closed")
    assert bool(stdout_handle.closed) is True


def test_runner_service_safe_name_and_dry_run() -> None:
    assert svc.safe_name("a b!c") == "abc"
    assert svc.safe_name("") == "tool"
    assert svc.dry_run_command(["echo", "hello world"], with_bashrc_fn=lambda cmd: f"bashrc:{cmd}").startswith("bashrc:")
