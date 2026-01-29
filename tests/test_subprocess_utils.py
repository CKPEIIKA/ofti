from unittest import mock

import pytest

from ofti.foam.subprocess_utils import resolve_executable, run_trusted


def test_resolve_executable_passes_absolute_path() -> None:
    assert resolve_executable("/bin/echo") == "/bin/echo"


def test_resolve_executable_uses_which(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/bin/{cmd}")
    assert resolve_executable("echo") == "/usr/bin/echo"


def test_resolve_executable_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _cmd: None)
    with pytest.raises(FileNotFoundError):
        resolve_executable("missing")


def test_run_trusted_executes(monkeypatch) -> None:
    _ = monkeypatch
    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "ok"
    completed.stderr = ""

    with mock.patch("ofti.foam.subprocess_utils.subprocess.run", return_value=completed) as run:
        result = run_trusted(["echo", "hi"])

    assert result is completed
    assert run.called
