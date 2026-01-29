from ofti.foamlib_runner import run_cases


def test_run_cases_empty() -> None:
    assert run_cases([]) == []
