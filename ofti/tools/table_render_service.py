from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ofti.core.table import render_kv, render_table


def preflight_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("solver", payload.get("solver_error") or payload.get("solver")),
            ("ok", payload.get("ok")),
        ],
    )
    checks = payload.get("checks", {})
    if isinstance(checks, dict):
        lines.extend(
            [
                "",
                "Checks",
                *render_table(
                    [
                        {"check": key, "status": "ok" if value else "missing"}
                        for key, value in checks.items()
                    ],
                    [("check", "Check"), ("status", "Status")],
                ),
            ],
        )
    return lines


def doctor_table_lines(payload: Mapping[str, Any]) -> list[str]:
    errors = list(payload.get("errors", []))
    warnings = list(payload.get("warnings", []))
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("errors", len(errors)),
            ("warnings", len(warnings)),
        ],
    )
    issue_rows = [
        {"level": "error", "message": item}
        for item in errors[:20]
    ] + [
        {"level": "warning", "message": item}
        for item in warnings[:20]
    ]
    if issue_rows:
        lines.extend(
            [
                "",
                "Issues",
                *render_table(issue_rows, [("level", "Level"), ("message", "Message")]),
            ],
        )
    if len(errors) > 20:
        lines.append(f"errors_more={len(errors) - 20}")
    if len(warnings) > 20:
        lines.append(f"warnings_more={len(warnings) - 20}")
    if not errors and not warnings:
        lines.append("OK: no issues found.")
    return lines


def status_table_lines(payload: Mapping[str, Any]) -> list[str]:
    rtc = _dict(payload.get("run_time_control"))
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("solver", payload.get("solver_error") or payload.get("solver")),
            ("solver_status", payload.get("solver_status") or "not tracked"),
            ("running", payload.get("running")),
            ("latest_time", payload.get("latest_time")),
            ("latest_iteration", payload.get("latest_iteration")),
            ("latest_delta_t", payload.get("latest_delta_t")),
            ("sec_per_iter", payload.get("sec_per_iter")),
            ("eta_to_criteria_start", payload.get("eta_seconds_to_criteria_start")),
            ("eta_to_end_time", payload.get("eta_seconds_to_end_time")),
            ("log", payload.get("log_path")),
            ("log_fresh", payload.get("log_fresh")),
            ("jobs_running", payload.get("jobs_running")),
            ("jobs_total", payload.get("jobs_total")),
        ],
    )
    criteria = _list(rtc.get("criteria"))
    lines.extend(
        [
            "",
            "Runtime control",
            *render_kv(
                [
                    ("criteria", len(criteria)),
                    ("pass", rtc.get("passed", 0)),
                    ("fail", rtc.get("failed", 0)),
                    ("unknown", rtc.get("unknown", 0)),
                ],
            ),
        ],
    )
    if criteria:
        lines.extend(["", "Criteria", *criteria_table_lines(criteria)])
    tracked = _list(payload.get("tracked_solver_processes"))
    untracked = _list(payload.get("untracked_solver_processes"))
    if tracked:
        lines.extend(["", "Tracked solver processes", *process_table_lines(tracked)])
    if untracked:
        lines.extend(["", "Untracked solver processes", *process_table_lines(untracked)])
    if payload.get("proc_access_warning"):
        lines.extend(_warning_lines(payload.get("proc_access_warning")))
    return lines


def current_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("scope", payload.get("scope")),
            ("cases_total", payload.get("cases_total")),
            ("solver", payload.get("solver_error") or payload.get("solver") or "mixed"),
            ("jobs_running", payload.get("jobs_running")),
            ("jobs_total", payload.get("jobs_total")),
            ("jobs_tracked_running", payload.get("jobs_tracked_running")),
            ("jobs_registry_running", payload.get("jobs_registry_running")),
        ],
    )
    if payload.get("proc_access_warning"):
        lines.extend(_warning_lines(payload.get("proc_access_warning")))
    jobs = list(payload.get("jobs", []))
    runs = list(payload.get("runs", []))
    if runs:
        lines.extend(["", "Runs", *runs_table_lines(runs)])
    elif jobs:
        lines.extend(["", "Tracked jobs", *jobs_table_lines(jobs)])
    untracked = list(payload.get("untracked_processes", []))
    if untracked:
        lines.extend(["", "Untracked solver processes", *process_table_lines(untracked)])
    if not runs and not jobs and not untracked:
        lines.append("No live jobs or solver processes detected.")
    return lines


def criteria_payload_table_lines(payload: Mapping[str, Any]) -> list[str]:
    criteria = list(payload.get("criteria", []))
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("solver", payload.get("solver_error") or payload.get("solver")),
            ("criteria", payload.get("criteria_count", len(criteria))),
            ("pass", payload.get("passed")),
            ("fail", payload.get("failed")),
            ("unknown", payload.get("unknown")),
            ("criteria_start", payload.get("criteria_start")),
            ("end_time", payload.get("end_time")),
            ("eta_to_criteria_start", payload.get("eta_to_criteria_start")),
        ],
    )
    if criteria:
        lines.extend(["", "Criteria", *criteria_table_lines(criteria)])
    return lines


def criteria_table_lines(rows: Sequence[object]) -> list[str]:
    return render_table(
        [_criteria_row(row) for row in rows],
        [
            ("name", "Name"),
            ("status", "Status"),
            ("value", "Value"),
            ("target", "Target"),
            ("tol", "Tol"),
            ("eta", "ETA(s)"),
            ("source", "Source"),
            ("unmet", "Unmet"),
            ("reason", "Reason"),
        ],
    )


def eta_table_lines(payload: Mapping[str, Any]) -> list[str]:
    return render_kv(
        [
            ("case", payload.get("case")),
            ("mode", payload.get("mode")),
            ("eta_mode", payload.get("eta_mode")),
            ("eta_reason", payload.get("eta_reason")),
            ("eta_confidence", payload.get("eta_confidence")),
            ("eta_seconds", payload.get("eta_seconds")),
            ("eta_criteria_seconds", payload.get("eta_criteria_seconds")),
            ("eta_end_time_seconds", payload.get("eta_end_time_seconds")),
            ("criteria_start", payload.get("criteria_start")),
            ("end_time", payload.get("end_time")),
            ("running", payload.get("running")),
        ],
    )


def report_table_lines(payload: Mapping[str, Any]) -> list[str]:
    log = _dict(payload.get("log"))
    metrics = _dict(payload.get("metrics"))
    criteria = _dict(payload.get("criteria"))
    eta = _dict(payload.get("eta"))
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("solver", payload.get("solver")),
            ("running", payload.get("running")),
            ("log", log.get("path")),
            ("log_fresh", log.get("fresh")),
            ("latest_time", metrics.get("latest_time")),
            ("latest_iteration", metrics.get("latest_iteration")),
            ("latest_delta_t", metrics.get("latest_delta_t")),
            ("sec_per_iter", metrics.get("sec_per_iter")),
            ("criteria", criteria.get("count")),
            ("pass", criteria.get("passed")),
            ("fail", criteria.get("failed")),
            ("unknown", criteria.get("unknown")),
            ("eta_criteria_seconds", eta.get("criteria_seconds")),
            ("eta_end_time_seconds", eta.get("end_time_seconds")),
            ("eta_criteria_start_seconds", eta.get("criteria_start_seconds")),
        ],
    )
    items = _list(criteria.get("items"))
    if items:
        lines.extend(["", "Criteria", *criteria_table_lines(items)])
    return lines


def metrics_table_lines(payload: Mapping[str, Any]) -> list[str]:
    execution = _dict(payload.get("execution_time"))
    times = _dict(payload.get("times"))
    courant = _dict(payload.get("courant"))
    return render_kv(
        [
            ("log", payload.get("log")),
            ("time_steps", times.get("count")),
            ("latest_time", times.get("last")),
            ("courant_count", courant.get("count")),
            ("courant_max", courant.get("max")),
            ("execution_points", execution.get("count")),
            ("execution_last", execution.get("last")),
            ("step_time_min", execution.get("delta_min")),
            ("step_time_avg", execution.get("delta_avg")),
            ("step_time_max", execution.get("delta_max")),
            ("residual_fields", ",".join(payload.get("residual_fields", []))),
        ],
    )


def residual_payload_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv([("log", payload.get("log"))])
    fields = _list(payload.get("fields"))
    if fields:
        lines.extend(["", *residuals_table_lines(fields)])
    return lines


def residuals_table_lines(rows: Sequence[object]) -> list[str]:
    return render_table(
        [_dict(row) for row in rows],
        [
            ("field", "Field"),
            ("count", "Count"),
            ("last", "Last"),
            ("min", "Min"),
            ("max", "Max"),
        ],
    )


def compare_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("left_case", payload.get("left_case")),
            ("right_case", payload.get("right_case")),
            ("diff_count", payload.get("diff_count")),
            ("flat", payload.get("flat")),
        ],
    )
    diffs = _list(payload.get("diffs"))
    if not diffs:
        lines.append("No dictionary key differences detected.")
        return lines
    lines.extend(["", "Diffs", *compare_diff_rows_table(diffs)])
    return lines


def initials_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("initial_dir", payload.get("initial_dir")),
            ("fields", payload.get("field_count")),
            ("patches", payload.get("patch_count")),
            ("failed", len(_list(payload.get("failed")))),
        ],
    )
    fields = _list(payload.get("fields"))
    if fields:
        lines.extend(["", "Fields", *initial_field_rows_table(fields)])
        boundary_rows = list(_initial_boundary_rows(fields))
        if boundary_rows:
            lines.extend(["", "Boundary conditions", *initial_boundary_rows_table(boundary_rows)])
    failed = _list(payload.get("failed"))
    if failed:
        lines.extend(
            [
                "",
                "Failed",
                *render_table(
                    [_dict(row) for row in failed],
                    [("path", "Path"), ("error", "Error")],
                ),
            ],
        )
    return lines


def converge_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("log", payload.get("log")),
            ("strict", payload.get("strict")),
            ("strict_ok", payload.get("strict_ok")),
            ("ok", payload.get("ok")),
        ],
    )
    rows = [
        {
            "check": "shock",
            "value": _dict(payload.get("shock")).get("drift"),
            "limit": _dict(payload.get("shock")).get("limit"),
            "ok": _dict(payload.get("shock")).get("ok"),
        },
        {
            "check": "drag",
            "value": _dict(payload.get("drag")).get("band"),
            "limit": _dict(payload.get("drag")).get("limit"),
            "ok": _dict(payload.get("drag")).get("ok"),
        },
        {
            "check": "mass",
            "value": _dict(payload.get("mass")).get("last_abs_global"),
            "limit": _dict(payload.get("mass")).get("limit"),
            "ok": _dict(payload.get("mass")).get("ok"),
        },
        {
            "check": "residuals",
            "value": "flatline" if _dict(payload.get("residuals")).get("flatline") else "ok",
            "limit": ",".join(
                str(item)
                for item in _list(_dict(payload.get("residuals")).get("flatline_fields"))
            ),
            "ok": not _dict(payload.get("residuals")).get("flatline"),
        },
        {
            "check": "thermo",
            "value": _dict(payload.get("thermo")).get("out_of_range_count"),
            "limit": 0,
            "ok": _dict(payload.get("thermo")).get("ok"),
        },
    ]
    lines.extend(
        [
            "",
            "Checks",
            *render_table(
                rows,
                [("check", "Check"), ("value", "Value"), ("limit", "Limit"), ("ok", "OK")],
            ),
        ],
    )
    return lines


def stability_table_lines(payload: Mapping[str, Any]) -> list[str]:
    return render_kv(
        [
            ("log", payload.get("log")),
            ("pattern", payload.get("pattern")),
            ("count", payload.get("count")),
            ("window", payload.get("window")),
            ("delta", payload.get("window_delta")),
            ("tolerance", payload.get("tolerance")),
            ("comparator", payload.get("comparator")),
            ("latest", payload.get("latest")),
            ("status", payload.get("status")),
            ("unmet_reason", payload.get("unmet_reason")),
            ("eta_seconds", payload.get("eta_seconds")),
        ],
    )


def compare_diff_rows_table(rows: Sequence[object]) -> list[str]:
    return render_table([_compare_diff_row(row) for row in rows], [
        ("file", "File"),
        ("kind", "Kind"),
        ("missing_left", "Missing left"),
        ("missing_right", "Missing right"),
        ("value_diffs", "Value diffs"),
        ("error", "Error"),
    ])


def initial_field_rows_table(rows: Sequence[object]) -> list[str]:
    return render_table(
        [_initial_field_row(row) for row in rows],
        [("field", "Field"), ("internal", "Internal"), ("patches", "Patches")],
    )


def initial_boundary_rows_table(rows: Sequence[object]) -> list[str]:
    return render_table(
        [_dict(row) for row in rows],
        [("field", "Field"), ("patch", "Patch"), ("type", "Type"), ("name", "Name")],
    )


def jobs_payload_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("kind", payload.get("kind")),
            ("count", payload.get("count")),
        ],
    )
    jobs = list(payload.get("jobs", []))
    runs = list(payload.get("runs", []))
    if runs:
        lines.extend(["", "Runs", *runs_table_lines(runs)])
    elif jobs:
        lines.extend(["", "Jobs", *jobs_table_lines(jobs)])
    else:
        lines.append("No tracked jobs.")
    return lines


def campaign_list_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("glob", payload.get("glob")),
            ("summary_csv", payload.get("summary_csv")),
            ("count", payload.get("count")),
        ],
    )
    cases = [{"case": case} for case in list(payload.get("cases", []))]
    if cases:
        lines.extend(["", "Cases", *render_table(cases, [("case", "Case")])])
    return lines


def campaign_status_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("glob", payload.get("glob")),
            ("summary_csv", payload.get("summary_csv")),
            ("count", payload.get("count")),
        ],
    )
    rows = list(payload.get("cases", []))
    if rows:
        lines.extend(["", "Cases", *campaign_case_rows_table(rows)])
    return lines


def campaign_rank_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("by", payload.get("by")),
            ("glob", payload.get("glob")),
            ("summary_csv", payload.get("summary_csv")),
            ("count", payload.get("count")),
        ],
    )
    rows = [
        {"rank": idx, **_dict(row)}
        for idx, row in enumerate(_list(payload.get("ranked")), start=1)
    ]
    if rows:
        lines.extend(["", "Ranked cases", *campaign_case_rows_table(rows, rank=True)])
    return lines


def campaign_compare_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("group_by", payload.get("group_by")),
            ("group_count", payload.get("group_count")),
            ("comparisons", len(_list(payload.get("comparisons")))),
        ],
    )
    groups = [
        {"group": key, "cases": len(_list(values))}
        for key, values in _dict(payload.get("groups")).items()
    ]
    if groups:
        lines.extend(
            ["", "Groups", *render_table(groups, [("group", "Group"), ("cases", "Cases")])],
        )
    return lines


def run_status_table_lines(payload: Mapping[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("set", payload.get("set_dir")),
            ("glob", payload.get("glob")),
            ("summary_csv", payload.get("summary_csv")),
            ("count", payload.get("count")),
        ],
    )
    rows = _list(payload.get("rows"))
    if rows:
        lines.extend(["", "Cases", *run_status_rows_table(rows)])
    return lines


def bundle_table_lines(payload: Mapping[str, Any]) -> list[str]:
    manifest = _dict(payload.get("manifest"))
    requirements = _dict(payload.get("requirements"))
    warnings = _list(manifest.get("warnings"))
    lines = render_kv(
        [
            ("archive", payload.get("archive")),
            ("case", payload.get("case_dir")),
            ("ok", payload.get("ok")),
            ("files", _file_count(manifest)),
            ("start_time", manifest.get("start_time")),
            ("solver", manifest.get("application")),
            ("openfoam_header", manifest.get("header_version")),
            ("mesh_included", requirements.get("mesh_included")),
            ("run_command", requirements.get("run_command")),
            ("next", payload.get("next")),
        ],
    )
    notes = _list(requirements.get("notes"))
    if notes:
        lines.extend(
            [
                "",
                "Target requirements",
                *render_table(_message_rows(notes), [("message", "Message")]),
            ],
        )
    if warnings:
        lines.extend(
            ["", "Warnings", *render_table(_message_rows(warnings), [("message", "Message")])],
        )
    smoke = _dict(payload.get("smoke"))
    if smoke:
        lines.extend(
            [
                "",
                "Smoke",
                *render_kv(
                    [
                        ("ok", smoke.get("ok")),
                        ("returncode", smoke.get("returncode")),
                        ("case", smoke.get("case")),
                        ("log", smoke.get("log_path")),
                    ],
                ),
            ],
        )
    return lines


def unbundle_table_lines(payload: Mapping[str, Any]) -> list[str]:
    manifest = _dict(payload.get("manifest"))
    requirements = _dict(payload.get("requirements"))
    warnings = _list(manifest.get("warnings"))
    lines = render_kv(
        [
            ("archive", payload.get("archive")),
            ("case", payload.get("case_dir")),
            ("ok", payload.get("ok")),
            ("files_verified", _file_count(manifest)),
            ("start_time", manifest.get("start_time")),
            ("solver", manifest.get("application")),
            ("openfoam_header", manifest.get("header_version")),
            ("mesh_included", requirements.get("mesh_included")),
            ("run_command", requirements.get("run_command")),
        ],
    )
    notes = _list(requirements.get("notes"))
    if notes:
        lines.extend(
            [
                "",
                "Target requirements",
                *render_table(_message_rows(notes), [("message", "Message")]),
            ],
        )
    run = _dict(payload.get("run"))
    if run:
        lines.extend(
            [
                "",
                "Run",
                *render_kv(
                    [
                        ("returncode", run.get("returncode")),
                        ("background", run.get("background")),
                        ("pid", run.get("pid")),
                        ("log", run.get("log")),
                        ("manifest", run.get("manifest")),
                    ],
                ),
            ],
        )
    else:
        lines.append(f"next={payload.get('next')}")
    if warnings:
        lines.extend(
            ["", "Warnings", *render_table(_message_rows(warnings), [("message", "Message")])],
        )
    return lines


def campaign_case_rows_table(rows: Sequence[object], *, rank: bool = False) -> list[str]:
    columns = [
        ("case", "Case"),
        ("running", "Running"),
        ("criteria_met", "Met"),
        ("criteria_total", "Total"),
        ("criteria_worst_ratio", "Worst"),
        ("latest_time", "Latest"),
        ("eta_seconds", "ETA(s)"),
    ]
    if rank:
        columns = [("rank", "#"), *columns]
    return render_table([_dict(row) for row in rows], columns)


def run_status_rows_table(rows: Sequence[object]) -> list[str]:
    return render_table(
        [_dict(row) for row in rows],
        [
            ("state", "State"),
            ("latest_time", "Latest"),
            ("eta_seconds", "ETA(s)"),
            ("stop_reason", "Stop reason"),
            ("jobs_running", "Jobs"),
            ("case", "Case"),
        ],
    )


def jobs_table_lines(rows: Sequence[object]) -> list[str]:
    return render_table(
        [_dict(row) for row in rows],
        [
            ("id", "ID"),
            ("kind", "Kind"),
            ("name", "Name"),
            ("pid", "PID"),
            ("status", "Status"),
            ("case", "Case"),
        ],
    )


def runs_table_lines(rows: Sequence[object]) -> list[str]:
    return render_table(
        [_dict(row) for row in rows],
        [
            ("id", "ID"),
            ("source", "Source"),
            ("name", "Name"),
            ("pid", "PID"),
            ("launcher_pid", "Launcher"),
            ("solver_pids", "Solvers"),
            ("status", "Status"),
            ("case_dir", "Case"),
        ],
    )


def process_table_lines(rows: Sequence[object]) -> list[str]:
    return render_table(
        [_dict(row) for row in rows],
        [
            ("pid", "PID"),
            ("role", "Role"),
            ("solver", "Solver"),
            ("case", "Case"),
            ("launcher_pid", "Launcher"),
            ("command", "Command"),
        ],
    )


def _criteria_row(row: object) -> dict[str, object]:
    data = _dict(row)
    return {
        "name": data.get("name") or data.get("key"),
        "status": data.get("status") or ("pass" if data.get("met") else "fail"),
        "value": data.get("value") or data.get("live_value"),
        "target": data.get("target") or data.get("value"),
        "tol": data.get("tol") or data.get("tolerance"),
        "eta": data.get("eta_seconds"),
        "source": data.get("source"),
        "unmet": data.get("unmet") or data.get("unmet_reason"),
    }


def _compare_diff_row(row: object) -> dict[str, object]:
    data = _dict(row)
    value_diffs = (
        data.get("value_diffs_flat")
        if data.get("value_diffs_flat")
        else data.get("value_diffs")
    )
    return {
        "file": data.get("rel_path"),
        "kind": data.get("kind", "dict"),
        "missing_left": len(_list(data.get("missing_in_left"))),
        "missing_right": len(_list(data.get("missing_in_right"))),
        "value_diffs": len(_list(value_diffs)),
        "error": data.get("error"),
    }


def _initial_field_row(row: object) -> dict[str, object]:
    data = _dict(row)
    boundary = _dict(data.get("boundary"))
    return {
        "field": data.get("name"),
        "internal": data.get("internal_field") or "<missing>",
        "patches": len(boundary),
    }


def _initial_boundary_rows(fields: list[object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for field in fields:
        field_data = _dict(field)
        for patch, patch_data in _dict(field_data.get("boundary")).items():
            patch_row = _dict(patch_data)
            rows.append(
                {
                    "field": field_data.get("name"),
                    "patch": patch,
                    "type": patch_row.get("type") or "missing",
                    "name": patch_row.get("name"),
                },
            )
    return rows


def _warning_lines(warning: object) -> list[str]:
    return ["", *render_kv([("proc_access_warning", warning)])]


def _file_count(manifest: Mapping[str, Any]) -> int:
    return len(_list(manifest.get("files")))


def _message_rows(messages: Sequence[object]) -> list[dict[str, str]]:
    return [{"message": str(message)} for message in messages]


def _list(value: object) -> list[object]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}
