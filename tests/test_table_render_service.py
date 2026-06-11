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

    lint = tables.lint_table_lines(
        {
            "case": "case",
            "errors": 0,
            "warnings": 1,
            "info": 0,
            "findings": [
                {
                    "severity": "WARN",
                    "rule": "pressure-reference",
                    "message": "missing pRefCell",
                    "evidence": "system/fvSolution",
                    "advice": "add pRefCell",
                },
            ],
        },
    )
    assert "Findings" in lint
    assert "pressure-reference" in "\n".join(lint)
    assert "OK" in tables.lint_table_lines({"case": "case", "findings": []})[-1]
    changes = tables.change_queue_table_lines(
        {
            "case": "case",
            "source": "git",
            "count": 1,
            "changes": [{"status": "M", "path": "system/controlDict"}],
            "actions": [{"action": "snapshot", "status": "recommended", "target": ".ofti/case_snapshot.json"}],
            "diff": ["diff --git a/system/controlDict b/system/controlDict"],
        },
    )
    assert "Pending case changes" in "\n".join(changes)
    assert "system/controlDict" in "\n".join(changes)
    assert "Change actions" in "\n".join(changes)
    assert "Diff preview" in "\n".join(changes)

    numerics = tables.numerics_table_lines(
        {
            "case": "case",
            "files": [{"file": "system/fvSolution", "status": "ok", "keys": "solvers"}],
            "controls": [{"key": "endTime", "value": "10", "status": "set"}],
            "solution": [{"key": "solvers", "value": "{}", "status": "set"}],
            "schemes": [{"key": "divSchemes", "value": "{}", "status": "set"}],
            "convergence_contract": [
                {"algorithm": "SIMPLE", "residualControl": "missing", "source": "system/fvSolution"},
            ],
            "presets": [
                {"name": "conservative steady RANS", "description": "stable", "changes": [{}]},
            ],
        },
    )
    numerics_text = "\n".join(numerics)
    assert "Numerics files" in numerics
    assert "Convergence contract" in numerics
    assert "Transparent presets" in numerics
    assert "Diff-before-write: yes" in numerics_text

    launch = tables.launch_checklist_table_lines(
        {
            "case": "case",
            "solver": "simpleFoam",
            "gate": "NO-GO",
            "ready": False,
            "rows": [{"item": "Mesh", "status": "fail", "required": True, "evidence": "x", "open": "constant/polyMesh"}],
            "log_strategy": {"log": "log.simpleFoam", "rotate_before_launch": True},
            "actions": [{"key": "1", "action": "open failing item", "target": "constant/polyMesh"}],
        },
    )
    launch_text = "\n".join(launch)
    assert "Go / no-go checklist" in launch
    assert "NO-GO" in launch_text
    assert "Log strategy" in launch
    assert "Actions" in launch

    flight = tables.flight_deck_table_lines(
        {
            "case": "case",
            "status": {"solver": "simpleFoam", "running": True},
            "current": {"jobs_running": 1},
            "criteria": {"criteria": [{"name": "U", "status": "pass", "value": 1}]},
            "control": {
                "path": "system/controlDict",
                "exists": True,
                "values": {"stopAt": "endTime", "endTime": "10", "deltaT": "1"},
                "runtime_modifiable": True,
            },
            "runtime_queue": [
                {
                    "key": "deltaT",
                    "status": "needs-value",
                    "action": "change deltaT",
                    "target": "system/controlDict:deltaT",
                    "change": "1 -> <prompt>",
                    "confirm": "watch log",
                },
            ],
            "actions": [{"key": "s", "action": "safe stop", "risk": "low"}],
        },
    )
    assert "Safe actions" in flight
    assert "Runtime mutation queue" in flight
    assert "Diff before apply: yes" in flight


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

    alerts = tables.alert_cards_table_lines(
        [
            {
                "severity": "WARN",
                "title": "High Courant",
                "evidence": "CoMax=2",
                "action": "reduce deltaT",
                "preview": "ofti plot metrics --table",
                "open": "system/controlDict",
            },
        ],
    )
    alert_text = "\n".join(alerts)
    assert "Alarm state: WARNING" in alert_text
    assert "High Courant" in alert_text
    assert "Impact" in alert_text
    assert "Preview" in alert_text
    assert "system/controlDict" in alert_text
    assert tables.alert_cards_table_lines([]) == ["Alarm state: NORMAL", "No alerts."]

    current_runs = tables.current_table_lines(
        {
            "case": "case",
            "solver": "simpleFoam",
            "jobs_running": 1,
            "jobs_total": 1,
            "jobs": [],
            "runs": [{"id": "r1", "source": "registry", "name": "simpleFoam", "pid": 11}],
            "untracked_processes": [],
        },
    )
    assert "Runs" in current_runs
    assert "registry" in "\n".join(current_runs)


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


def test_live_cases_catalog_and_receipt_tables() -> None:
    live_cases = tables.live_cases_table_lines(
        {
            "set_dir": "root",
            "glob": "*",
            "summary_csv": None,
            "count": 1,
            "group_state": True,
            "rows": [
                {"case": "case_1", "state": "running", "jobs_running": 1},
                {"case": "case_2", "state": "queued", "jobs_running": 0},
            ],
        },
    )
    live_text = "\n".join(live_cases)
    assert "Case grid" in live_cases
    assert "running" in live_text
    assert "State: running" in live_text
    assert "queued" in live_text
    assert "case_1" in live_text

    dna = tables.case_dna_table_lines(
        {
            "case": "case",
            "solver": "simpleFoam",
            "running": True,
            "latest_time": 1,
            "latest_iteration": 2,
            "fields": 3,
            "patches": 4,
            "residual_fields": ["Ux", "p"],
            "jobs_running": 1,
            "criteria_failed": 0,
            "risk": "low",
            "fingerprint": {"hash": "abc", "files": 3, "skipped": 0},
        },
    )
    dna_text = "\n".join(dna)
    assert "risk" in dna_text
    assert "abc" in dna_text

    scopes = tables.scope_table_lines({"rows": [{"scope": "Courant max", "value": 0.5, "plot": "██"}]})
    assert "Courant max" in "\n".join(scopes)
    assert tables.scope_table_lines({"rows": []}) == ["No scope data available."]

    folded = tables.folded_log_table_lines(
        {"log": "log.simpleFoam", "rows": [{"kind": "time", "message": "Time = 1"}]},
    )
    assert "Signals" in folded

    radar = tables.mesh_radar_table_lines(
        {
            "case": "case",
            "status": "warn",
            "has_mesh": True,
            "log": "log.checkMesh",
            "metrics": [{"metric": "Max non-orth", "value": 72.0, "status": "warn", "bar_value": 72, "bar_max": 80}],
            "advice": [{"issue": "High non-orthogonality", "advice": "inspect mesh"}],
            "notes": ["Failed checks: 1"],
        },
    )
    radar_text = "\n".join(radar)
    assert "Mesh quality" in radar
    assert "Max non-orth" in radar_text
    assert "Advice" in radar
    assert "inspect mesh" in radar_text
    assert "Notes" in radar

    resources = tables.resource_watch_table_lines(
        {
            "case": "case",
            "risk": "low",
            "free_bytes": 1024,
            "time_dirs": 2,
            "processor_dirs": 1,
            "log_bytes": 10,
            "disk_growth": {
                "source": "logs",
                "rate": "10B/h",
                "eta_to_full": "4d 6h",
                "evidence": "10B across 1 log file(s)",
            },
            "write_settings": {"writeControl": "timeStep", "writeInterval": "10", "purgeWrite": "0"},
            "cleanup_actions": [{"key": "z", "action": "compress logs", "target": "log.*", "safe": False}],
            "suggestions": ["Review write settings."],
            "logs": [{"log": "log.simpleFoam", "size": "10B"}],
        },
    )
    resources_text = "\n".join(resources)
    assert "free_disk" in resources_text
    assert "Disk growth" in resources
    assert "Write settings" in resources
    assert "Cleanup actions" in resources
    assert "Suggestions" in resources
    assert "Logs" in resources
    assert "log.simpleFoam" in resources_text

    captains_deck = tables.captains_deck_table_lines(
        {
            "case": "case",
            "case_dna": {"case": "case", "risk": "low", "fingerprint": {"hash": "abc"}},
            "scopes": {"rows": [{"scope": "Courant max", "value": 0.5, "plot": "██"}]},
            "mesh_radar": {"case": "case", "status": "ok", "metrics": [], "notes": []},
            "resource_watch": {"case": "case", "risk": "low", "logs": []},
        },
    )
    captains_deck_text = "\n".join(captains_deck)
    assert "Case DNA" in captains_deck_text
    assert "Mission Scopes" in captains_deck_text
    assert "Resource Watch" in captains_deck_text

    monitors = tables.monitor_builder_table_lines(
        {
            "case": "case",
            "target": "case/system/controlDict.functions",
            "configured": False,
            "changed": True,
            "written": False,
            "activation": "include system/controlDict.functions",
            "monitors": [
                {
                    "monitor": "residuals",
                    "status": "planned",
                    "writes": "system/controlDict.functions",
                    "note": "live residual scope",
                },
            ],
            "diff": ["--- old", "+++ new"],
        },
    )
    monitors_text = "\n".join(monitors)
    assert "Monitor plan" in monitors
    assert "residuals" in monitors_text
    assert "Diff preview" in monitors

    resize = tables.parallel_resize_table_lines(
        {
            "case": "case",
            "ok": True,
            "from": 2,
            "to": 4,
            "dry_run": True,
            "start": False,
            "steps": [
                {
                    "step": "decompose",
                    "status": "pending",
                    "label": "decompose latest",
                    "command": "decomposePar -force -latestTime",
                },
            ],
        },
    )
    resize_text = "\n".join(resize)
    assert "Parallel resize plan" in resize
    assert "decomposePar -force -latestTime" in resize_text

    catalog = tables.tool_catalog_table_lines({"case": "case", "tools": ["blockMesh"]})
    assert "Tools" in catalog
    assert "blockMesh" in "\n".join(catalog)

    receipt = tables.receipt_verify_table_lines(
        {
            "receipt": "runs/receipt.json",
            "case": "case",
            "ok": False,
            "expected_tree_hash": "a",
            "actual_tree_hash": "b",
            "recorded_inputs_copy": True,
            "restorable": True,
            "openfoam": {"match": True},
            "build": {"solver": {"match": False}, "linked_libs": {"match": True}},
            "missing_files": [],
            "changed_files": [{"path": "system/controlDict"}],
            "extra_files": ["system/newDict"],
        },
    )
    receipt_text = "\n".join(receipt)
    assert "Checks" in receipt
    assert "Changed files" in receipt
    assert "system/controlDict" in receipt_text
