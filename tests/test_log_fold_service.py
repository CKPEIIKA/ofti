from __future__ import annotations

from ofti.tools.log_fold_service import fold_log_lines


def test_fold_log_lines_keeps_solver_signals_and_folds_noise() -> None:
    rows = fold_log_lines(
        [
            "Time = 1",
            "smoothSolver: Solving for Ux, Initial residual = 1e-3, Final residual = 1e-4",
            "Courant Number mean: 0.2 max: 0.5",
            "plain solver chatter",
            "WARNING: something odd",
            "ExecutionTime = 4 s",
        ],
    )
    text = "\n".join(str(row) for row in rows)
    assert "time" in text
    assert "residual" in text
    assert "courant" in text
    assert "warning" in text
    assert "runtime" in text
    assert "1 other lines" in text


def test_fold_log_lines_limits_signal_rows() -> None:
    rows = fold_log_lines(["Time = 1", "Time = 2", "Time = 3"], limit=2)

    assert len(rows) == 3
    assert rows[-1]["kind"] == "folded"
