from ofti.foamlib_runner import run_cases


def test_run_cases_empty() -> None:
    assert run_cases([]) == []


def test_run_cases_stops_on_failure_when_check_true(monkeypatch, tmp_path) -> None:
    called = []

    def boom(path, *_args, **_kwargs):
        called.append(path)
        raise RuntimeError("fail")

    monkeypatch.setattr("ofti.foamlib_runner.run_case", boom)
    failures = run_cases([tmp_path / "a", tmp_path / "b"], check=True)
    assert failures == [tmp_path / "a"]
    assert called == [tmp_path / "a"]


def test_run_cases_continues_on_failure_when_check_false(monkeypatch, tmp_path) -> None:
    called = []

    def boom(path, *_args, **_kwargs):
        called.append(path)
        raise RuntimeError("fail")

    monkeypatch.setattr("ofti.foamlib_runner.run_case", boom)
    failures = run_cases([tmp_path / "a", tmp_path / "b"], check=False)
    assert failures == [tmp_path / "a", tmp_path / "b"]
    assert called == [tmp_path / "a", tmp_path / "b"]
