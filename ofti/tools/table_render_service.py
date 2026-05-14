from __future__ import annotations

from typing import Any

from ofti.core.plot import block_bar
from ofti.core.table import render_kv, render_table


def preflight_table_lines(payload: dict[str, Any]) -> list[str]:
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


def doctor_table_lines(payload: dict[str, Any]) -> list[str]:
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


def lint_table_lines(payload: dict[str, Any]) -> list[str]:
    findings = [_dict(row) for row in list(payload.get("findings", []))]
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("errors", payload.get("errors")),
            ("warnings", payload.get("warnings")),
            ("info", payload.get("info")),
        ],
    )
    if findings:
        lines.extend(
            [
                "",
                "Findings",
                *render_table(
                    findings,
                    [
                        ("severity", "Severity"),
                        ("rule", "Rule"),
                        ("message", "Message"),
                        ("evidence", "Evidence"),
                        ("advice", "Advice"),
                    ],
                ),
            ],
        )
    else:
        lines.append("OK: no lint findings.")
    return lines


def status_table_lines(payload: dict[str, Any]) -> list[str]:
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
    criteria = list(rtc.get("criteria", []))
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
    tracked = list(payload.get("tracked_solver_processes", []))
    untracked = list(payload.get("untracked_solver_processes", []))
    if tracked:
        lines.extend(["", "Tracked solver processes", *process_table_lines(tracked)])
    if untracked:
        lines.extend(["", "Untracked solver processes", *process_table_lines(untracked)])
    if payload.get("proc_access_warning"):
        lines.extend(_warning_lines(payload.get("proc_access_warning")))
    return lines


def current_table_lines(payload: dict[str, Any]) -> list[str]:
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
    if jobs:
        lines.extend(["", "Tracked jobs", *jobs_table_lines(jobs)])
    untracked = list(payload.get("untracked_processes", []))
    if untracked:
        lines.extend(["", "Untracked solver processes", *process_table_lines(untracked)])
    if not jobs and not untracked:
        lines.append("No live jobs or solver processes detected.")
    return lines


def alert_cards_table_lines(cards: list[object]) -> list[str]:
    rows = [_dict(card) for card in cards]
    if not rows:
        return ["No alerts."]
    return render_table(
        rows,
        [
            ("severity", "Severity"),
            ("title", "Alert"),
            ("evidence", "Evidence"),
            ("action", "Action"),
            ("source", "Source"),
        ],
    )


def criteria_payload_table_lines(payload: dict[str, Any]) -> list[str]:
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


def criteria_table_lines(rows: list[object]) -> list[str]:
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
        ],
    )


def eta_table_lines(payload: dict[str, Any]) -> list[str]:
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


def report_table_lines(payload: dict[str, Any]) -> list[str]:
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
    items = list(criteria.get("items", []))
    if items:
        lines.extend(["", "Criteria", *criteria_table_lines(items)])
    return lines


def metrics_table_lines(payload: dict[str, Any]) -> list[str]:
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


def residual_payload_table_lines(payload: dict[str, Any]) -> list[str]:
    lines = render_kv([("log", payload.get("log"))])
    fields = list(payload.get("fields", []))
    if fields:
        lines.extend(["", *residuals_table_lines(fields)])
    return lines


def residuals_table_lines(rows: list[object]) -> list[str]:
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


def case_dna_table_lines(payload: dict[str, Any]) -> list[str]:
    residual_fields = ",".join(str(item) for item in list(payload.get("residual_fields", [])))
    fingerprint = _dict(payload.get("fingerprint"))
    return render_kv(
        [
            ("case", payload.get("case")),
            ("solver", payload.get("solver")),
            ("running", payload.get("running")),
            ("latest_time", payload.get("latest_time")),
            ("latest_iteration", payload.get("latest_iteration")),
            ("fields", payload.get("fields")),
            ("patches", payload.get("patches")),
            ("residual_fields", residual_fields),
            ("jobs_running", payload.get("jobs_running")),
            ("criteria_failed", payload.get("criteria_failed")),
            ("risk", payload.get("risk")),
            ("fingerprint", fingerprint.get("hash")),
            ("fingerprint_files", fingerprint.get("files")),
            ("fingerprint_skipped", fingerprint.get("skipped")),
        ],
    )


def scope_table_lines(payload: dict[str, Any]) -> list[str]:
    rows = [_dict(row) for row in list(payload.get("rows", []))]
    if not rows:
        return ["No scope data available."]
    return render_table(rows, [("scope", "Scope"), ("value", "Value"), ("plot", "Plot")])


def folded_log_table_lines(payload: dict[str, Any]) -> list[str]:
    rows = [_dict(row) for row in list(payload.get("rows", []))]
    lines = render_kv([("log", payload.get("log")), ("signals", len(rows))])
    if rows:
        lines.extend(
            [
                "",
                "Signals",
                *render_table(rows, [("kind", "Kind"), ("message", "Message")]),
            ],
        )
    else:
        lines.append("No signal lines found.")
    return lines


def mesh_radar_table_lines(payload: dict[str, Any]) -> list[str]:
    metrics = [_mesh_radar_row(row) for row in list(payload.get("metrics", []))]
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("status", payload.get("status")),
            ("has_mesh", payload.get("has_mesh")),
            ("log", payload.get("log")),
        ],
    )
    if metrics:
        lines.extend(
            [
                "",
                "Mesh quality",
                *render_table(
                    metrics,
                    [
                        ("metric", "Metric"),
                        ("value", "Value"),
                        ("status", "Status"),
                        ("bar", "Radar"),
                    ],
                ),
            ],
        )
    advice = [_dict(row) for row in list(payload.get("advice", []))]
    if advice:
        lines.extend(
            [
                "",
                "Advice",
                *render_table(advice, [("issue", "Issue"), ("advice", "Advice")]),
            ],
        )
    notes = [{"note": note} for note in list(payload.get("notes", []))]
    if notes:
        lines.extend(["", "Notes", *render_table(notes, [("note", "Note")])])
    return lines


def resource_watch_table_lines(payload: dict[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("risk", payload.get("risk")),
            ("free_disk", _format_bytes_value(payload.get("free_bytes"))),
            ("time_dirs", payload.get("time_dirs")),
            ("processor_dirs", payload.get("processor_dirs")),
            ("log_total", _format_bytes_value(payload.get("log_bytes"))),
        ],
    )
    write_settings = _dict(payload.get("write_settings"))
    if write_settings:
        lines.extend(
            [
                "",
                "Write settings",
                *render_kv(
                    [
                        ("writeControl", write_settings.get("writeControl")),
                        ("writeInterval", write_settings.get("writeInterval")),
                        ("purgeWrite", write_settings.get("purgeWrite")),
                    ],
                ),
            ],
        )
    suggestions = [{"suggestion": item} for item in list(payload.get("suggestions", []))]
    if suggestions:
        lines.extend(
            ["", "Suggestions", *render_table(suggestions, [("suggestion", "Suggestion")])],
        )
    logs = list(payload.get("logs", []))
    if logs:
        lines.extend(
            [
                "",
                "Logs",
                *render_table([_dict(row) for row in logs], [("log", "Log"), ("size", "Size")]),
            ],
        )
    return lines


def change_queue_table_lines(payload: dict[str, Any]) -> list[str]:
    changes = [_dict(row) for row in list(payload.get("changes", []))]
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("source", payload.get("source")),
            ("pending_changes", payload.get("count")),
            ("error", payload.get("error")),
        ],
    )
    if changes:
        lines.extend(
            [
                "",
                "Pending case changes",
                *render_table(changes, [("status", "Status"), ("path", "Path")]),
            ],
        )
    else:
        paths = ", ".join(str(item) for item in list(payload.get("paths", [])))
        lines.append(f"No pending VCS-backed case changes found for: {paths}")
    if payload.get("diff_error"):
        lines.append(f"diff_error={payload.get('diff_error')}")
    diff = [str(line) for line in list(payload.get("diff", []))]
    if diff:
        lines.extend(["", "Diff preview", *diff])
    return lines


def numerics_table_lines(payload: dict[str, Any]) -> list[str]:
    lines = render_kv([("case", payload.get("case"))])
    files = [_dict(row) for row in list(payload.get("files", []))]
    if files:
        lines.extend(
            [
                "",
                "Numerics files",
                *render_table(files, [("file", "File"), ("status", "Status"), ("keys", "Keys")]),
            ],
        )
    controls = [_dict(row) for row in list(payload.get("controls", []))]
    if controls:
        lines.extend(
            [
                "",
                "Time controls",
                *render_table(controls, [("key", "Key"), ("value", "Value"), ("status", "Status")]),
            ],
        )
    solution = [_dict(row) for row in list(payload.get("solution", []))]
    if solution:
        lines.extend(
            [
                "",
                "Solution controls",
                *render_table(solution, [("key", "Key"), ("value", "Value"), ("status", "Status")]),
            ],
        )
    return lines


def launch_checklist_table_lines(payload: dict[str, Any]) -> list[str]:
    rows = [_dict(row) for row in list(payload.get("rows", []))]
    lines = render_kv([("case", payload.get("case")), ("ready", payload.get("ready"))])
    if rows:
        lines.extend(
            [
                "",
                "Go / no-go checklist",
                *render_table(
                    rows,
                    [
                        ("item", "Item"),
                        ("status", "Status"),
                        ("required", "Required"),
                        ("evidence", "Evidence"),
                        ("advice", "Advice"),
                    ],
                ),
            ],
        )
    return lines


def monitor_builder_table_lines(payload: dict[str, Any]) -> list[str]:
    rows = [_dict(row) for row in list(payload.get("monitors", []))]
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("target", payload.get("target")),
            ("configured", payload.get("configured")),
            ("changed", payload.get("changed")),
            ("written", payload.get("written")),
            ("activation", payload.get("activation")),
        ],
    )
    if rows:
        lines.extend(
            [
                "",
                "Monitor plan",
                *render_table(
                    rows,
                    [
                        ("monitor", "Monitor"),
                        ("status", "Status"),
                        ("writes", "Writes"),
                        ("note", "Note"),
                    ],
                ),
            ],
        )
    diff = [str(line) for line in list(payload.get("diff", []))]
    if diff:
        lines.extend(["", "Diff preview", *diff[:80]])
        if len(diff) > 80:
            lines.append(f"... {len(diff) - 80} more")
    return lines


def parallel_resize_table_lines(payload: dict[str, Any]) -> list[str]:
    steps = [_dict(row) for row in list(payload.get("steps", []))]
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("ok", payload.get("ok")),
            ("from", payload.get("from")),
            ("to", payload.get("to")),
            ("dry_run", payload.get("dry_run")),
            ("start", payload.get("start")),
            ("pid", payload.get("pid")),
            ("log", payload.get("log_path")),
            ("error", payload.get("error")),
        ],
    )
    if steps:
        lines.extend(
            [
                "",
                "Parallel resize plan",
                *render_table(
                    steps,
                    [
                        ("step", "Step"),
                        ("status", "Status"),
                        ("label", "Action"),
                        ("command", "Command"),
                    ],
                ),
            ],
        )
    return lines


def flight_deck_table_lines(payload: dict[str, Any]) -> list[str]:
    status = _dict(payload.get("status"))
    current = _dict(payload.get("current"))
    criteria = _dict(payload.get("criteria"))
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("solver", status.get("solver_error") or status.get("solver")),
            ("running", status.get("running")),
            ("jobs_running", current.get("jobs_running")),
            ("latest_time", status.get("latest_time")),
            ("eta_to_end_time", status.get("eta_seconds_to_end_time")),
        ],
    )
    criteria_rows = [_dict(row) for row in list(criteria.get("criteria", []))]
    if criteria_rows:
        lines.extend(
            [
                "",
                "Runtime criteria",
                *render_table(
                    criteria_rows,
                    [
                        ("name", "Name"),
                        ("status", "Status"),
                        ("value", "Value"),
                        ("target", "Target"),
                    ],
                ),
            ],
        )
    actions = [_dict(row) for row in list(payload.get("actions", []))]
    if actions:
        lines.extend(
            [
                "",
                "Safe actions",
                *render_table(actions, [("key", "Key"), ("action", "Action"), ("risk", "Risk")]),
            ],
        )
    return lines


def captains_deck_table_lines(payload: dict[str, Any]) -> list[str]:
    sections = [
        ("Case DNA", case_dna_table_lines(_dict(payload.get("case_dna")))),
        ("Mission Scopes", scope_table_lines(_dict(payload.get("scopes")))),
        ("Mesh Radar", mesh_radar_table_lines(_dict(payload.get("mesh_radar")))),
        ("Resource Watch", resource_watch_table_lines(_dict(payload.get("resource_watch")))),
    ]
    lines = render_kv([("case", payload.get("case"))])
    for title, section_lines in sections:
        lines.extend(["", title, "-" * len(title), *section_lines])
    return lines


def compare_table_lines(payload: dict[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("left_case", payload.get("left_case")),
            ("right_case", payload.get("right_case")),
            ("diff_count", payload.get("diff_count")),
            ("flat", payload.get("flat")),
        ],
    )
    diffs = list(payload.get("diffs", []))
    if not diffs:
        lines.append("No dictionary key differences detected.")
        return lines
    lines.extend(["", "Diffs", *compare_diff_rows_table(diffs)])
    return lines


def initials_table_lines(payload: dict[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("initial_dir", payload.get("initial_dir")),
            ("fields", payload.get("field_count")),
            ("patches", payload.get("patch_count")),
            ("failed", len(list(payload.get("failed", [])))),
        ],
    )
    fields = list(payload.get("fields", []))
    if fields:
        lines.extend(["", "Fields", *initial_field_rows_table(fields)])
        boundary_rows = list(_initial_boundary_rows(fields))
        if boundary_rows:
            lines.extend(["", "Boundary conditions", *initial_boundary_rows_table(boundary_rows)])
    failed = list(payload.get("failed", []))
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


def converge_table_lines(payload: dict[str, Any]) -> list[str]:
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
            "limit": ",".join(_dict(payload.get("residuals")).get("flatline_fields", [])),
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


def stability_table_lines(payload: dict[str, Any]) -> list[str]:
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


def compare_diff_rows_table(rows: list[object]) -> list[str]:
    return render_table([_compare_diff_row(row) for row in rows], [
        ("file", "File"),
        ("kind", "Kind"),
        ("missing_left", "Missing left"),
        ("missing_right", "Missing right"),
        ("value_diffs", "Value diffs"),
        ("error", "Error"),
    ])


def initial_field_rows_table(rows: list[object]) -> list[str]:
    return render_table(
        [_initial_field_row(row) for row in rows],
        [("field", "Field"), ("internal", "Internal"), ("patches", "Patches")],
    )


def initial_boundary_rows_table(rows: list[object]) -> list[str]:
    return render_table(
        [_dict(row) for row in rows],
        [("field", "Field"), ("patch", "Patch"), ("type", "Type"), ("name", "Name")],
    )


def jobs_payload_table_lines(payload: dict[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("kind", payload.get("kind")),
            ("count", payload.get("count")),
        ],
    )
    jobs = list(payload.get("jobs", []))
    if jobs:
        lines.extend(["", "Jobs", *jobs_table_lines(jobs)])
    else:
        lines.append("No tracked jobs.")
    return lines


def live_cases_table_lines(payload: dict[str, Any]) -> list[str]:
    rows = list(payload.get("rows", []))
    state_counts: dict[str, int] = {}
    for row in rows:
        state = str(_dict(row).get("state") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
    lines = render_kv(
        [
            ("set", payload.get("set_dir")),
            ("glob", payload.get("glob")),
            ("summary_csv", payload.get("summary_csv")),
            ("count", payload.get("count", len(rows))),
            ("running", state_counts.get("running", 0)),
            ("queued", state_counts.get("queued", 0)),
            ("done", state_counts.get("done", 0)),
            ("failed", state_counts.get("failed", 0)),
            ("unknown", state_counts.get("unknown", 0)),
        ],
    )
    if rows:
        if payload.get("group_state"):
            lines.extend(["", "Case grid"])
            for state in _state_order(rows):
                state_rows = [
                    row for row in rows
                    if str(_dict(row).get("state") or "unknown") == state
                ]
                lines.extend(
                    [f"State: {state} ({len(state_rows)})", *run_status_rows_table(state_rows)],
                )
        else:
            lines.extend(["", "Case grid", *run_status_rows_table(rows)])
    else:
        lines.append("No cases found.")
    return lines


def tool_catalog_table_lines(payload: dict[str, Any]) -> list[str]:
    tools = [{"tool": name} for name in list(payload.get("tools", []))]
    lines = render_kv([("case", payload.get("case")), ("tools", len(tools))])
    if tools:
        lines.extend(["", "Tools", *render_table(tools, [("tool", "Tool")])])
    return lines


def receipt_verify_table_lines(payload: dict[str, Any]) -> list[str]:
    openfoam = _dict(payload.get("openfoam"))
    build = _dict(payload.get("build"))
    solver = _dict(build.get("solver"))
    linked_libs = _dict(build.get("linked_libs"))
    missing = list(payload.get("missing_files", []))
    changed = list(payload.get("changed_files", []))
    extra = list(payload.get("extra_files", []))
    lines = render_kv(
        [
            ("receipt", payload.get("receipt")),
            ("case", payload.get("case")),
            ("ok", payload.get("ok")),
            ("expected_tree_hash", payload.get("expected_tree_hash")),
            ("actual_tree_hash", payload.get("actual_tree_hash")),
            ("recorded_inputs_copy", payload.get("recorded_inputs_copy")),
            ("restorable", payload.get("restorable")),
        ],
    )
    checks = [
        {"check": "openfoam_version", "match": openfoam.get("match")},
        {"check": "solver_binary", "match": solver.get("match")},
        {"check": "linked_libs", "match": linked_libs.get("match")},
        {"check": "missing_files", "match": not missing, "count": len(missing)},
        {"check": "changed_files", "match": not changed, "count": len(changed)},
        {"check": "extra_files", "match": not extra, "count": len(extra)},
    ]
    lines.extend(
        [
            "",
            "Checks",
            *render_table(checks, [("check", "Check"), ("match", "Match"), ("count", "Count")]),
        ],
    )
    if changed:
        changed_paths = [_dict(row).get("path") for row in changed]
        lines.extend(_single_path_table("Changed files", changed_paths))
    if missing:
        lines.extend(_single_path_table("Missing files", missing))
    if extra:
        lines.extend(_single_path_table("Extra files", extra))
    return lines


def campaign_list_table_lines(payload: dict[str, Any]) -> list[str]:
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


def campaign_status_table_lines(payload: dict[str, Any]) -> list[str]:
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


def campaign_rank_table_lines(payload: dict[str, Any]) -> list[str]:
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
        for idx, row in enumerate(list(payload.get("ranked", [])), start=1)
    ]
    if rows:
        lines.extend(["", "Ranked cases", *campaign_case_rows_table(rows, rank=True)])
    return lines


def campaign_compare_table_lines(payload: dict[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("case", payload.get("case")),
            ("group_by", payload.get("group_by")),
            ("group_count", payload.get("group_count")),
            ("comparisons", len(list(payload.get("comparisons", [])))),
        ],
    )
    groups = [
        {"group": key, "cases": len(list(values))}
        for key, values in _dict(payload.get("groups")).items()
    ]
    if groups:
        lines.extend(
            ["", "Groups", *render_table(groups, [("group", "Group"), ("cases", "Cases")])],
        )
    return lines


def run_status_table_lines(payload: dict[str, Any]) -> list[str]:
    lines = render_kv(
        [
            ("set", payload.get("set_dir")),
            ("glob", payload.get("glob")),
            ("summary_csv", payload.get("summary_csv")),
            ("count", payload.get("count")),
        ],
    )
    rows = list(payload.get("rows", []))
    if rows:
        lines.extend(["", "Cases", *run_status_rows_table(rows)])
    return lines


def campaign_case_rows_table(rows: list[object], *, rank: bool = False) -> list[str]:
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


def run_status_rows_table(rows: list[object]) -> list[str]:
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


def jobs_table_lines(rows: list[object]) -> list[str]:
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


def process_table_lines(rows: list[object]) -> list[str]:
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
        "missing_left": len(list(data.get("missing_in_left", []))),
        "missing_right": len(list(data.get("missing_in_right", []))),
        "value_diffs": len(list(value_diffs or [])),
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


def _single_path_table(title: str, paths: list[object]) -> list[str]:
    return ["", title, *render_table([{"path": path} for path in paths], [("path", "Path")])]


def _warning_lines(warning: object) -> list[str]:
    return ["", *render_kv([("proc_access_warning", warning)])]


def _mesh_radar_row(row: object) -> dict[str, object]:
    data = _dict(row)
    return {
        "metric": data.get("metric"),
        "value": data.get("value"),
        "status": data.get("status"),
        "bar": block_bar(
            _float_or_none(data.get("bar_value")),
            maximum=_float_or_none(data.get("bar_max")),
            width=16,
        ),
    }


def _state_order(rows: list[object]) -> list[str]:
    wanted = ["running", "queued", "failed", "done", "unknown"]
    states = {str(_dict(row).get("state") or "unknown") for row in rows}
    return [state for state in wanted if state in states] + sorted(states.difference(wanted))


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _format_bytes_value(value: object) -> str | None:
    number = _float_or_none(value)
    if number is None:
        return None
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{number:.1f}{unit}" if unit != "B" else f"{int(number)}B"
        number /= 1024
    return f"{number:.1f}TB"


def _dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}
