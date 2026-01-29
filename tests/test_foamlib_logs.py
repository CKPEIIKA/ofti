from ofti.foamlib_logs import (
    execution_time_deltas,
    parse_courant_numbers,
    parse_execution_times,
    parse_log_metrics,
    parse_residuals,
    parse_time_steps,
)


def test_parse_residuals() -> None:
    text = """
    Solving for Ux, Initial residual = 0.01, Final residual = 0.001, No Iterations 1
    Solving for Uy, Initial residual = 0.02, Final residual = 0.002, No Iterations 1
    Solving for p, Initial residual = 0.03, Final residual = 0.003, No Iterations 2
    """
    result = parse_residuals(text)
    assert result["Ux"] == [0.01]
    assert result["Uy"] == [0.02]
    assert result["p"] == [0.03]


def test_parse_time_and_courant_and_exec() -> None:
    text = """
    Time = 0.1
    Courant Number mean: 0.05 max: 0.9
    ExecutionTime = 1.2 s  ClockTime = 1 s
    Time = 0.2
    Courant Number mean: 0.02 max: 0.8
    ExecutionTime = 2.4 s  ClockTime = 2 s
    """
    assert parse_time_steps(text) == [0.1, 0.2]
    assert parse_courant_numbers(text) == [0.9, 0.8]
    assert parse_execution_times(text) == [1.2, 2.4]
    metrics = parse_log_metrics(text)
    assert metrics.times == [0.1, 0.2]
    assert metrics.courants == [0.9, 0.8]
    assert metrics.execution_times == [1.2, 2.4]
    assert execution_time_deltas(metrics.execution_times) == [1.2]
