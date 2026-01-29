from ofti.foamlib_logs import parse_residuals


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
