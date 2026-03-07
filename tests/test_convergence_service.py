from __future__ import annotations

from pathlib import Path

from ofti.tools import convergence_service as svc


def test_convergence_payload_strict_and_non_strict() -> None:
    log_path = Path("log.hy2Foam")
    text = "\n".join(
        [
            "shockPosition = 0.1",
            "shockPosition = 0.11",
            "Cd = 0.50",
            "Cd = 0.5001",
            "continuity errors : global = 1e-06",
            "temperature out of range",
        ],
    )
    residuals = {
        "U": [1.0, 0.8, 0.7, 0.7],
        "p": [1.0, 0.1, 0.01, 0.001],
    }

    relaxed = svc.converge_from_text(
        log_path,
        text,
        residuals=residuals,
        strict=False,
        shock_drift_limit=0.02,
        drag_band_limit=0.02,
        mass_limit=1e-4,
    )
    assert relaxed["thermo"]["ok"] is False
    assert relaxed["strict_ok"] is True
    assert relaxed["ok"] is False

    strict = svc.converge_from_text(
        log_path,
        text,
        residuals=residuals,
        strict=True,
        shock_drift_limit=0.02,
        drag_band_limit=0.02,
        mass_limit=1e-4,
    )
    assert strict["strict"] is True
    assert strict["strict_ok"] is True
    assert strict["ok"] is True


def test_convergence_helpers() -> None:
    values = svc.collect_floats(["Cd = 0.1", "Cd = nope"], svc.DRAG_RE)
    assert values == [0.1]
    assert svc.band([1.0, 2.5, 0.5]) == 2.0
    assert svc.band([]) is None
    assert svc.to_float("1.5;") == 1.5
    assert svc.to_float("bad") is None


def test_windowed_stability_and_series_extract() -> None:
    values = svc.extract_series(
        "\n".join(
            [
                "Cd = 0.20",
                "Cd = 0.18",
                "Cd = 0.17",
                "Cd = 0.1705",
            ],
        ),
        r"Cd\s*=\s*(?P<value>[0-9eE.+-]+)",
    )
    assert values == [0.2, 0.18, 0.17, 0.1705]

    startup = svc.windowed_stability(values[:1], tolerance=0.01, window=3, startup_samples=2)
    assert startup["unmet_reason"] == "startup"

    not_enough = svc.windowed_stability(values[:2], tolerance=0.01, window=4, startup_samples=0)
    assert not_enough["unmet_reason"] == "not_enough_samples"

    stable = svc.windowed_stability(values, tolerance=0.04, window=3, startup_samples=0)
    assert stable["status"] == "pass"
    assert stable["eta_seconds"] == 0.0


def test_stability_from_text_payload() -> None:
    log = Path("log.simpleFoam")
    text = "\n".join(
        [
            "ExecutionTime = 1.0 s",
            "Cd = 0.30",
            "ExecutionTime = 2.0 s",
            "Cd = 0.25",
            "ExecutionTime = 3.0 s",
            "Cd = 0.22",
            "ExecutionTime = 4.0 s",
            "Cd = 0.21",
        ],
    )
    payload = svc.stability_from_text(
        log,
        text,
        pattern=r"Cd\s*=\s*(?P<value>[0-9eE.+-]+)",
        tolerance=0.05,
        window=3,
        startup_samples=0,
        comparator="le",
    )
    assert payload["log"] == str(log)
    assert payload["status"] in {"pass", "fail"}
    assert payload["window"] == 3
