import types
from pathlib import Path

import pytest

from ofti.foamlib import runner
from ofti.foamlib.runner import run_cases


def test_run_cases_empty() -> None:
    assert run_cases([]) == []


def test_run_cases_stops_on_failure_when_check_true(monkeypatch, tmp_path) -> None:
    called = []

    def boom(path, *_args, **_kwargs):
        called.append(path)
        raise RuntimeError("fail")

    monkeypatch.setattr("ofti.foamlib.runner.run_case", boom)
    failures = run_cases([tmp_path / "a", tmp_path / "b"], check=True)
    assert failures == [tmp_path / "a"]
    assert called == [tmp_path / "a"]


def test_run_cases_continues_on_failure_when_check_false(monkeypatch, tmp_path) -> None:
    called = []

    def boom(path, *_args, **_kwargs):
        called.append(path)
        raise RuntimeError("fail")

    monkeypatch.setattr("ofti.foamlib.runner.run_case", boom)
    failures = run_cases([tmp_path / "a", tmp_path / "b"], check=False)
    assert failures == [tmp_path / "a", tmp_path / "b"]
    assert called == [tmp_path / "a", tmp_path / "b"]


def test_runner_case_lifecycle_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, object]] = []

    class _FakeCase:
        def __init__(self, path: Path) -> None:
            self.path = path

        def copy(self, dst: Path) -> types.SimpleNamespace:
            calls.append(("copy", dst))
            return types.SimpleNamespace(path=dst)

        def clone(self, dst: Path) -> types.SimpleNamespace:
            calls.append(("clone", dst))
            return types.SimpleNamespace(path=dst)

        def clean(self, *, check: bool = False) -> None:
            calls.append(("clean", check))

        def decompose_par(self, *, check: bool = True, log: bool | str = True) -> None:
            calls.append(("decompose", (check, log)))

    monkeypatch.setattr(runner, "FoamCase", _FakeCase)
    monkeypatch.setattr(runner, "available", lambda: True)

    dst_copy = runner.copy_case(tmp_path / "case", tmp_path / "copy")
    dst_clone = runner.clone_case(tmp_path / "case", tmp_path / "clone")
    runner.clean_case(tmp_path / "case", check=True)
    runner.decompose_case(tmp_path / "case", check=False, log="log.decompose")

    assert dst_copy == (tmp_path / "copy").resolve()
    assert dst_clone == (tmp_path / "clone").resolve()
    assert ("copy", tmp_path / "copy") in calls
    assert ("clone", tmp_path / "clone") in calls
    assert ("clean", True) in calls
    assert ("decompose", (False, "log.decompose")) in calls


def test_run_cases_async_uses_backend_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _AsyncCase:
        def __init__(self, _path: Path) -> None:
            pass

        async def run(self, *_args, **_kwargs) -> None:
            return None

    class _AsyncSlurmCase:
        def __init__(self, _path: Path) -> None:
            pass

        async def run(self, *_args, **kwargs) -> None:
            assert kwargs["fallback"] is True

    monkeypatch.setattr(runner, "AsyncFoamCase", _AsyncCase)
    monkeypatch.setattr(runner, "AsyncSlurmFoamCase", _AsyncSlurmCase)
    monkeypatch.setattr(runner, "available", lambda: True)

    ok = runner.run_cases_async([tmp_path / "a"], check=False, max_parallel=1, slurm=False)
    assert ok == []
    ok_slurm = runner.run_cases_async(
        [tmp_path / "a"],
        check=False,
        max_parallel=1,
        slurm=True,
        fallback=True,
    )
    assert ok_slurm == []
