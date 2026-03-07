from __future__ import annotations

from pathlib import Path

from ofti.tools import runtime_control_service as svc


def _make_case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "0").mkdir()
    (path / "0" / "U").write_text("placeholder\n")
    return path


def test_runtime_control_snapshot_reads_include_and_metrics(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    include_file = case / "system" / "criteria.inc"
    include_file.write_text("residualTolerance 0.01;\n")
    (case / "system" / "controlDict").write_text(
        "\n".join(
            [
                "startTime 0;",
                "endTime 2;",
                '#include "$FOAM_CASE/system/criteria.inc"',
                "functions",
                "{",
                "  autoStop",
                "  {",
                "    type runTimeControl;",
                "    timeStart 0.5;",
                "    conditions",
                "    {",
                "      shockFlat",
                "      {",
                "        type average;",
                "        value 100;",
                "      }",
                "    }",
                "  }",
                "}",
            ],
        ),
    )
    log_path = case / "log.hy2Foam"
    log_path.write_text(
        "\n".join(
            [
                "Time = 0.1",
                "ExecutionTime = 0.5 s",
                "Time = 0.2",
                "ExecutionTime = 1.0 s",
                "deltaT = 0.01",
                "iter = 7",
                "residualTolerance passed",
                "shockFlat satisfied",
            ],
        ),
    )

    snapshot = svc.runtime_control_snapshot(
        case,
        "hy2Foam",
        resolve_log_source_fn=lambda source: source / "log.hy2Foam",
    )

    assert snapshot["latest_time"] == 0.2
    assert snapshot["latest_iteration"] == 7
    assert snapshot["latest_delta_t"] == 0.01
    assert snapshot["run_time_control"]["end_time"] == 2.0
    assert snapshot["run_time_control"]["criteria_start"] == 0.5
    assert snapshot["run_time_control"]["passed"] >= 1


def test_runtime_control_resolve_solver_log_fallback(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    (case / "log.simpleFoam").write_text("Time = 1\n")

    found = svc.resolve_solver_log(
        case,
        "simpleFoam",
        resolve_log_source_fn=lambda _source: (_source / "missing"),
    )
    assert found == (case / "log.simpleFoam").resolve()

    missing = svc.resolve_solver_log(
        case,
        "hy2Foam",
        resolve_log_source_fn=lambda _source: (_ for _ in ()).throw(ValueError("none")),
    )
    assert missing is None


def test_runtime_control_enriches_live_criterion_values(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    (case / "system" / "controlDict").write_text("startTime 0;\nendTime 1;\nresidualTolerance 0.05;\n")
    (case / "log.hy2Foam").write_text(
        "\n".join(
            [
                "Time = 0.1",
                "ExecutionTime = 1.0 s",
                "residualTolerance value = 0.20",
                "Time = 0.2",
                "ExecutionTime = 2.0 s",
                "residualTolerance value = 0.10",
                "Time = 0.3",
                "ExecutionTime = 3.0 s",
                "residualTolerance value = 0.04",
            ],
        ),
    )

    snapshot = svc.runtime_control_snapshot(
        case,
        "hy2Foam",
        resolve_log_source_fn=lambda source: source / "log.hy2Foam",
    )
    criteria = snapshot["run_time_control"]["criteria"]
    assert criteria
    row = criteria[0]
    assert row["tolerance"] == 0.05
    assert row["live_value"] == 0.04
    assert row["status"] == "pass"
    assert row["eta_seconds"] == 0.0
    assert row["unmet_reason"] is None


def test_runtime_control_marks_startup_unmet_reason(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    (case / "system" / "controlDict").write_text(
        "\n".join(
            [
                "startTime 0;",
                "endTime 4;",
                "functions",
                "{",
                "  stopper",
                "  {",
                "    type runTimeControl;",
                "    timeStart 2;",
                "    conditions",
                "    {",
                "      residualGate",
                "      {",
                "        type average;",
                "        value 0.01;",
                "      }",
                "    }",
                "  }",
                "}",
            ],
        ),
    )
    (case / "log.hy2Foam").write_text(
        "\n".join(
            [
                "Time = 0.1",
                "ExecutionTime = 1.0 s",
                "Time = 0.2",
                "ExecutionTime = 2.0 s",
            ],
        ),
    )

    snapshot = svc.runtime_control_snapshot(
        case,
        "hy2Foam",
        resolve_log_source_fn=lambda source: source / "log.hy2Foam",
    )
    rows = snapshot["run_time_control"]["criteria"]
    assert rows
    assert rows[0]["unmet_reason"] == "startup"
