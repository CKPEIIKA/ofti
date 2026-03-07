from pathlib import Path

from ofti.foamlib.logs import (
    execution_time_deltas,
    parse_courant_numbers,
    parse_execution_times,
    parse_log_metrics,
    parse_log_metrics_and_residuals,
    parse_residuals,
    parse_time_steps,
    read_log_tail_lines,
    read_log_text,
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
    combined_metrics, combined_residuals = parse_log_metrics_and_residuals(text)
    assert combined_metrics == metrics
    assert combined_residuals == {}
    assert execution_time_deltas(metrics.execution_times) == [1.2]


def test_read_log_tail_lines(tmp_path: Path) -> None:
    path = tmp_path / "log.simpleFoam"
    path.write_text("\n".join(f"line-{idx}" for idx in range(1, 21)) + "\n")
    lines = read_log_tail_lines(path, max_lines=3, max_bytes=1024)
    assert lines == ["line-18", "line-19", "line-20"]


def test_read_log_text_is_capped_and_line_aligned(tmp_path: Path) -> None:
    path = tmp_path / "log.hy2Foam"
    path.write_text("\n".join([f"keep-{idx}" for idx in range(1, 6)] + [f"tail-{idx}" for idx in range(6, 11)]) + "\n")
    full = read_log_text(path, max_bytes=None)
    assert "keep-1" in full
    capped = read_log_text(path, max_bytes=32)
    assert "tail-10" in capped
    assert "keep-1" not in capped
