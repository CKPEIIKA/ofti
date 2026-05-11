from __future__ import annotations

from ofti.core.table import render_table
from ofti.tools import table_render_service as tables


def test_render_table_empty_and_scalar_formatting() -> None:
    assert render_table([], [("name", "Name")]) == ["(none)"]
    lines = render_table(
        [{"name": "ok", "enabled": True, "ratio": 0.123456789, "missing": None}],
        [
            ("name", "Name"),
            ("enabled", "Enabled"),
            ("ratio", "Ratio"),
            ("missing", "Missing"),
        ],
    )
    assert "yes" in "\n".join(lines)
    assert "0.123457" in "\n".join(lines)
    assert "-" in lines[-1]


def test_table_render_service_branches() -> None:
    preflight = tables.preflight_table_lines(
        {
            "case": "case",
            "ok": False,
            "checks": {"system/controlDict": True, "solver_entry": False},
            "solver_error": "missing solver",
        },
    )
    assert "Checks" in preflight
    assert "missing solver" in "\n".join(preflight)

    doctor = tables.doctor_table_lines(
        {
            "case": "case",
            "errors": [f"e{i}" for i in range(21)],
            "warnings": [f"w{i}" for i in range(21)],
        },
    )
    assert "Issues" in doctor
    assert "errors_more=1" in doctor
    assert "warnings_more=1" in doctor

    clean_doctor = tables.doctor_table_lines({"case": "case", "errors": [], "warnings": []})
    assert "OK: no issues found." in clean_doctor


def test_runtime_tables_cover_nested_rows() -> None:
    status = tables.status_table_lines(
        {
            "case": "case",
            "solver": "simpleFoam",
            "solver_error": None,
            "solver_status": "running",
            "running": True,
            "run_time_control": {
                "criteria": [
                    {
                        "key": "residual",
                        "met": False,
                        "live_value": 0.2,
                        "target": 0.01,
                        "tolerance": 0.001,
                        "eta_seconds": 5.0,
                        "source": "runTimeControl",
                    },
                ],
                "passed": 0,
                "failed": 1,
                "unknown": 0,
            },
            "tracked_solver_processes": [{"pid": 1, "solver": "simpleFoam", "tracked": True}],
            "untracked_solver_processes": [{"pid": 2, "solver": "simpleFoam"}],
            "proc_access_warning": "limited proc",
        },
    )
    text = "\n".join(status)
    assert "Criteria" in status
    assert "residual" in text
    assert "Tracked solver processes" in status
    assert "Untracked solver processes" in status
    assert "limited proc" in text

    current = tables.current_table_lines(
        {
            "case": "case",
            "solver": None,
            "solver_error": None,
            "jobs_running": 0,
            "jobs_total": 0,
            "jobs": [],
            "untracked_processes": [],
        },
    )
    assert "No live jobs or solver processes detected." in current


def test_payload_tables_for_cli_outputs() -> None:
    criteria = tables.criteria_payload_table_lines(
        {
            "case": "case",
            "solver": "simpleFoam",
            "criteria_count": 1,
            "passed": 1,
            "failed": 0,
            "unknown": 0,
            "criteria": [{"name": "force", "status": "pass", "value": 1.0}],
        },
    )
    assert "force" in "\n".join(criteria)

    eta = tables.eta_table_lines(
        {
            "case": "case",
            "mode": "criteria",
            "eta_mode": "criteria",
            "eta_reason": "all met",
            "eta_confidence": "high",
            "eta_seconds": 0,
        },
    )
    assert "eta_confidence" in "\n".join(eta)

    report = tables.report_table_lines(
        {
            "case": "case",
            "solver": "simpleFoam",
            "running": False,
            "log": {"path": "log.simpleFoam", "fresh": False},
            "metrics": {"latest_time": 1.0, "latest_iteration": 3},
            "criteria": {"count": 1, "passed": 1, "items": [{"name": "force"}]},
            "eta": {"criteria_seconds": 0},
        },
    )
    assert "force" in "\n".join(report)

    residuals = tables.residual_payload_table_lines(
        {
            "log": "log.simpleFoam",
            "fields": [{"field": "Ux", "count": 2, "last": 0.1, "min": 0.1, "max": 1.0}],
        },
    )
    assert "Ux" in "\n".join(residuals)

    jobs = tables.jobs_payload_table_lines({"case": "case", "kind": "any", "count": 0, "jobs": []})
    assert "No tracked jobs." in jobs


def test_readonly_diagnostic_tables() -> None:
    compare = tables.compare_table_lines(
        {
            "left_case": "a",
            "right_case": "b",
            "diff_count": 1,
            "flat": False,
            "diffs": [
                {
                    "rel_path": "system/controlDict",
                    "kind": "dict",
                    "missing_in_left": ["endTime"],
                    "missing_in_right": [],
                    "value_diffs": [{"key": "application", "left": "a", "right": "b"}],
                    "error": None,
                },
            ],
        },
    )
    assert "Diffs" in compare
    assert "system/controlDict" in "\n".join(compare)

    initials = tables.initials_table_lines(
        {
            "case": "case",
            "initial_dir": "0",
            "field_count": 1,
            "patch_count": 1,
            "fields": [
                {
                    "name": "U",
                    "internal_field": "uniform (1 0 0)",
                    "boundary": {"inlet": {"type": "fixedValue", "name": "U"}},
                },
            ],
            "failed": [],
        },
    )
    assert "Boundary conditions" in initials
    assert "fixedValue" in "\n".join(initials)

    converge = tables.converge_table_lines(
        {
            "log": "log.simpleFoam",
            "strict": False,
            "strict_ok": True,
            "ok": True,
            "shock": {"drift": 0.01, "limit": 0.02, "ok": True},
            "drag": {"band": 0.01, "limit": 0.02, "ok": True},
            "mass": {"last_abs_global": 1e-5, "limit": 1e-4, "ok": True},
            "residuals": {"flatline": False, "flatline_fields": []},
            "thermo": {"out_of_range_count": 0, "ok": True},
        },
    )
    assert "Checks" in converge
    assert "shock" in "\n".join(converge)

    stability = tables.stability_table_lines(
        {
            "log": "log.simpleFoam",
            "pattern": "Cd",
            "count": 10,
            "window": 8,
            "window_delta": 0.01,
            "tolerance": 0.02,
            "comparator": "le",
            "latest": 0.41,
            "status": "pass",
            "unmet_reason": None,
            "eta_seconds": 0,
        },
    )
    stability_text = "\n".join(stability)
    assert "status" in stability_text
    assert "pass" in stability_text


def test_campaign_and_run_status_tables() -> None:
    cases_payload = {
        "case": "root",
        "glob": "case_*",
        "summary_csv": None,
        "count": 1,
        "cases": ["root/case_1"],
    }
    assert "root/case_1" in "\n".join(tables.campaign_list_table_lines(cases_payload))

    case_row = {
        "case": "root/case_1",
        "running": True,
        "criteria_met": 1,
        "criteria_total": 2,
        "criteria_worst_ratio": 0.5,
        "latest_time": 3.0,
        "eta_seconds": 4.0,
    }
    assert "Worst" in "\n".join(tables.campaign_status_table_lines({**cases_payload, "cases": [case_row]}))
    assert "Ranked cases" in tables.campaign_rank_table_lines(
        {**cases_payload, "by": "convergence", "ranked": [case_row]},
    )
    assert "Groups" in tables.campaign_compare_table_lines(
        {"case": "root", "group_by": "speed", "group_count": 1, "groups": {"fast": ["case_1"]}},
    )
    run_status = tables.run_status_table_lines(
        {
            "set_dir": "root",
            "glob": "case_*",
            "summary_csv": None,
            "count": 1,
            "rows": [{"case": "root/case_1", "state": "running", "jobs_running": 1}],
        },
    )
    assert "Stop reason" in "\n".join(run_status)
