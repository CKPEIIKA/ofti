from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.helpers import show_message
from ofti.tools import status_render_service
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.input_prompts import prompt_line
from ofti.ui_curses.viewer import Viewer


def show_preflight_screen(stdscr: Any, case_path: Path) -> None:
    try:
        payload = knife_ops.preflight_payload(case_path)
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    lines = [f"case={payload['case']}"]
    for key, value in payload["checks"].items():
        lines.append(f"{key}={'ok' if value else 'missing'}")
    if payload.get("solver_error"):
        lines.append(f"solver_error={payload['solver_error']}")
    lines.append(f"ok={payload['ok']}")
    Viewer(stdscr, "\n".join(lines)).display()


def show_case_status_screen(stdscr: Any, case_path: Path) -> None:
    try:
        payload = knife_ops.status_payload(case_path)
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    Viewer(stdscr, "\n".join(status_render_service.case_status_lines(payload))).display()


def show_current_jobs_screen(stdscr: Any, case_path: Path, *, live: bool = True) -> None:
    try:
        payload = knife_ops.current_payload(case_path, live=live)
    except TypeError:
        payload = knife_ops.current_payload(case_path)
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    lines = [
        f"case={payload['case']}",
        (
            f"solver_error={payload['solver_error']}"
            if payload.get("solver_error")
            else f"solver={payload.get('solver')}"
        ),
        f"jobs_running={payload.get('jobs_running', 0)}",
    ]
    jobs = list(payload.get("jobs", []))
    if jobs:
        lines.append("")
        lines.append("tracked_jobs:")
        for row in jobs:
            lines.append(
                f"- id={row.get('id')} pid={row.get('pid')} "
                f"name={row.get('name')} status={row.get('status')}",
            )
    untracked = list(payload.get("untracked_processes", []))
    if untracked:
        lines.append("")
        lines.append("untracked_processes:")
        for row in untracked[:40]:
            lines.append(
                f"- pid={row.get('pid')} role={row.get('role')} "
                f"solver={row.get('solver')} launcher_pid={row.get('launcher_pid')} "
                f"cmd={row.get('command')}",
            )
        if len(untracked) > 40:
            lines.append(f"... {len(untracked) - 40} more")
    Viewer(stdscr, "\n".join(lines)).display()


def adopt_untracked_screen(stdscr: Any, case_path: Path, *, recursive: bool = False) -> None:
    try:
        payload = knife_ops.adopt_payload(case_path, recursive=recursive)
    except TypeError:
        payload = knife_ops.adopt_payload(case_path)
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    lines = [
        f"case={payload['case']}",
        f"scope={payload.get('scope', 'case')}",
        f"selected={payload.get('selected', 0)}",
        f"adopted={len(payload.get('adopted', []))}",
    ]
    for key in ("jobs_running_before", "jobs_running_after"):
        if key in payload:
            lines.append(f"{key}={payload[key]}")
    adopted = list(payload.get("adopted", []))
    if adopted:
        lines.append("")
        lines.append("adopted_rows:")
        for row in adopted:
            lines.append(
                f"- id={row.get('id')} pid={row.get('pid')} "
                f"case={row.get('case')} name={row.get('name')} role={row.get('role')}",
            )
    failed = list(payload.get("failed", []))
    if failed:
        lines.append("")
        lines.append("failed:")
        for row in failed:
            lines.append(
                f"- pid={row.get('pid')} case={row.get('case')} error={row.get('error')}",
            )
    Viewer(stdscr, "\n".join(lines)).display()


def compare_dictionaries_screen(stdscr: Any, case_path: Path) -> None:
    other = prompt_line(stdscr, "Compare with case path: ")
    if not other:
        return
    try:
        payload = knife_ops.compare_payload(case_path, Path(other))
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    Viewer(stdscr, "\n".join(compare_lines(payload))).display()


def compare_lines(payload: dict[str, Any]) -> list[str]:
    lines = [
        f"left_case={payload['left_case']}",
        f"right_case={payload['right_case']}",
        f"diff_count={payload['diff_count']}",
    ]
    for diff in payload["diffs"]:
        lines.append("")
        lines.append(str(diff["rel_path"]))
        if diff.get("error"):
            lines.append(f"  error: {diff['error']}")
        if diff.get("missing_in_left"):
            lines.append(f"  missing_in_left: {', '.join(diff['missing_in_left'])}")
        if diff.get("missing_in_right"):
            lines.append(f"  missing_in_right: {', '.join(diff['missing_in_right'])}")
        value_diffs = list(diff.get("value_diffs", []))
        for row in value_diffs[:20]:
            lines.append(f"  {row['key']}: left={row['left']} right={row['right']}")
        if len(value_diffs) > 20:
            lines.append(f"  value_diff_more={len(value_diffs) - 20}")
    return lines


def show_initial_fields_screen(stdscr: Any, case_path: Path) -> None:
    try:
        payload = knife_ops.initials_payload(case_path)
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    lines = [
        f"case={payload['case']}",
        f"initial_dir={payload['initial_dir']}",
        f"fields={payload['field_count']} patches={payload['patch_count']}",
    ]
    for field in payload.get("fields", []):
        lines.append("")
        lines.append(f"[{field.get('name')}]")
        lines.append(f"internalField={field.get('internal_field') or '<missing>'}")
        boundary = field.get("boundary", {})
        if not boundary:
            lines.append("boundary=<none>")
            continue
        for patch in sorted(boundary):
            row = boundary[patch] or {}
            lines.append(
                f"- {patch}: type={row.get('type') or 'missing'} value={row.get('value') or ''}",
            )
    Viewer(stdscr, "\n".join(lines)).display()


def set_dictionary_entry_screen(stdscr: Any, case_path: Path) -> None:
    rel_file = prompt_line(stdscr, "Dictionary file (e.g. system/controlDict): ")
    if not rel_file:
        return
    key = prompt_line(stdscr, "Entry key (dot path): ")
    if not key:
        return
    value = prompt_line(stdscr, "Entry value: ")
    if value is None:
        return
    try:
        payload = knife_ops.set_entry_payload(case_path, rel_file, key, value)
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    lines = [
        f"case={payload['case']}",
        f"file={payload['file']}",
        f"key={payload['key']}",
        f"value={payload['value']}",
        f"ok={payload['ok']}",
    ]
    Viewer(stdscr, "\n".join(lines)).display()


def show_runtime_criteria_screen(stdscr: Any, case_path: Path) -> None:
    try:
        payload = knife_ops.criteria_payload(case_path)
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    lines = [
        f"case={payload['case']}",
        (
            f"solver_error={payload['solver_error']}"
            if payload.get("solver_error")
            else f"solver={payload.get('solver')}"
        ),
        (
            f"criteria={payload['criteria_count']} pass={payload['passed']} "
            f"fail={payload['failed']} unknown={payload['unknown']}"
        ),
    ]
    for row in payload.get("criteria", []):
        lines.append(
            f"- {row.get('name')}: met={row.get('met')} value={row.get('value')} "
            f"tol={row.get('tol')} unmet={row.get('unmet')} source={row.get('source')}",
        )
    Viewer(stdscr, "\n".join(lines)).display()


def show_eta_forecast_screen(stdscr: Any, case_path: Path) -> None:
    mode_raw = prompt_line(stdscr, "ETA mode [auto|criteria|end] (default auto): ")
    if mode_raw is None:
        return
    mode = (mode_raw or "auto").strip().lower()
    if mode not in {"auto", "criteria", "end"}:
        show_message(stdscr, "Unsupported ETA mode. Use auto, criteria, or end.")
        return
    try:
        payload = knife_ops.eta_payload(case_path, mode=mode)
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    lines = [
        f"case={payload['case']}",
        f"mode={payload['mode']}",
        f"eta_mode={payload.get('eta_mode')}",
        f"eta_reason={payload.get('eta_reason')}",
        f"eta_confidence={payload.get('eta_confidence')}",
        f"eta_seconds={payload.get('eta_seconds')}",
        f"eta_criteria_seconds={payload.get('eta_criteria_seconds')}",
        f"eta_end_time_seconds={payload.get('eta_end_time_seconds')}",
    ]
    Viewer(stdscr, "\n".join(lines)).display()


def show_runtime_report_screen(stdscr: Any, case_path: Path) -> None:
    try:
        payload = knife_ops.report_payload(case_path)
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    Viewer(stdscr, knife_ops.report_markdown(payload)).display()


def run_convergence_check_screen(stdscr: Any, case_path: Path) -> None:
    strict_raw = prompt_line(stdscr, "Strict mode? [y/N]: ")
    if strict_raw is None:
        return
    strict = strict_raw.strip().lower() in {"y", "yes", "1", "true"}
    try:
        payload = knife_ops.converge_payload(case_path, strict=strict)
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    lines = [
        f"log={payload['log']}",
        (
            f"shock drift={payload['shock']['drift']} limit={payload['shock']['limit']} "
            f"ok={payload['shock']['ok']}"
        ),
        (
            f"drag band={payload['drag']['band']} limit={payload['drag']['limit']} "
            f"ok={payload['drag']['ok']}"
        ),
        (
            "mass "
            f"last_abs_global={payload['mass']['last_abs_global']} "
            f"limit={payload['mass']['limit']} ok={payload['mass']['ok']}"
        ),
        (
            f"residuals flatline={payload['residuals']['flatline']} "
            f"fields={','.join(payload['residuals']['flatline_fields'])}"
        ),
        (
            f"thermo out_of_range_count={payload['thermo']['out_of_range_count']} "
            f"ok={payload['thermo']['ok']}"
        ),
        f"strict={payload['strict']} strict_ok={payload['strict_ok']}",
        f"ok={payload['ok']}",
    ]
    Viewer(stdscr, "\n".join(lines)).display()


def run_stability_check_screen(stdscr: Any, case_path: Path) -> None:
    params = _stability_prompt_config(stdscr)
    if params is None:
        return
    try:
        payload = knife_ops.stability_payload(
            case_path,
            pattern=str(params["pattern"]),
            tolerance=float(params["tolerance"]),
            window=int(params["window"]),
            startup_samples=int(params["startup_samples"]),
            comparator=str(params["comparator"]),
        )
    except ValueError as exc:
        show_message(stdscr, str(exc))
        return
    lines = [
        f"log={payload['log']}",
        f"pattern={payload['pattern']}",
        (
            f"count={payload['count']} window={payload['window']} "
            f"delta={payload['window_delta']} tolerance={payload['tolerance']} "
            f"comparator={payload['comparator']}"
        ),
        f"latest={payload['latest']}",
        f"status={payload['status']} unmet_reason={payload['unmet_reason']}",
        f"eta_seconds={payload['eta_seconds']}",
    ]
    Viewer(stdscr, "\n".join(lines)).display()


def _stability_prompt_config(stdscr: Any) -> dict[str, Any] | None:
    pattern_raw = prompt_line(stdscr, "Pattern (default: Courant Number mean): ")
    tolerance = _prompt_float(stdscr, "Tolerance (default 0.02): ", default=0.02)
    window = _prompt_int(stdscr, "Window samples (default 50): ", default=50)
    startup = _prompt_int(stdscr, "Startup samples ignored (default 0): ", default=0)
    comparator_raw = prompt_line(stdscr, "Comparator [le|lt|ge|gt] (default le): ")
    values = (pattern_raw, tolerance, window, startup, comparator_raw)
    if any(value is None for value in values):
        return None
    comparator = (str(comparator_raw) or "le").strip().lower()
    if comparator not in {"le", "lt", "ge", "gt"}:
        show_message(stdscr, "Unsupported comparator. Use le, lt, ge, or gt.")
        return None
    return {
        "pattern": (str(pattern_raw) or "Courant Number mean").strip(),
        "tolerance": float(tolerance),
        "window": int(window),
        "startup_samples": int(startup),
        "comparator": comparator,
    }


def _prompt_float(stdscr: Any, prompt: str, *, default: float) -> float | None:
    raw = prompt_line(stdscr, prompt)
    if raw is None:
        return None
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        show_message(stdscr, f"Invalid float value: {raw}")
        return None


def _prompt_int(stdscr: Any, prompt: str, *, default: int) -> int | None:
    raw = prompt_line(stdscr, prompt)
    if raw is None:
        return None
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        show_message(stdscr, f"Invalid integer value: {raw}")
        return None
