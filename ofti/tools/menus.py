from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from ofti.tools import (
    case_doctor,
    case_ops,
    cleaning_ops,
    diagnostics,
    job_control,
    logs_analysis,
    logs_fields,
    logs_probes,
    logs_view,
    mesh_utils,
    parametric,
    pipeline,
    postprocessing,
    reconstruct,
    run,
    shell_tools,
    solver,
    solver_control,
    status_render_service,
    time_pruner,
    tool_dicts_foamcalc,
    tool_dicts_postprocess,
    yplus,
)
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.input_prompts import prompt_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import (
    _no_foam_active,
    _normalize_tool_name,
    _run_simple_tool,
    _show_message,
    get_last_tool_run,
    last_tool_status_line,
    load_postprocessing_presets,
    load_tool_presets,
    tool_status_mode,
)
from ofti.tools.tool_aliases import STATIC_TOOL_ALIAS_GROUPS
from ofti.ui.help import menu_hint, tools_help, tools_physics_help
from ofti.ui_curses.blockmesh_helper import blockmesh_helper_screen
from ofti.ui_curses.boundary_matrix import boundary_matrix_screen
from ofti.ui_curses.high_speed import high_speed_helper_screen
from ofti.ui_curses.initial_conditions import initial_conditions_screen
from ofti.ui_curses.snappy_toggle import snappy_staged_screen
from ofti.ui_curses.thermo_wizard import thermophysical_wizard_screen
from ofti.ui_curses.viewer import Viewer

clean_time_directories = cleaning_ops.clean_time_directories
clone_case = case_ops.clone_case
diagnostics_screen = diagnostics.diagnostics_screen
foam_calc_prompt = tool_dicts_foamcalc.foam_calc_prompt
log_analysis_screen = logs_analysis.log_analysis_screen
field_summary_screen = logs_fields.field_summary_screen
logs_screen = logs_view.logs_screen
pipeline_editor_screen = pipeline.pipeline_editor_screen
pipeline_runner_screen = pipeline.pipeline_runner_screen
foamlib_parametric_study_screen = parametric.foamlib_parametric_study_screen
open_paraview_screen = case_ops.open_paraview_screen
post_process_prompt = tool_dicts_postprocess.post_process_prompt
probes_viewer_screen = logs_probes.probes_viewer_screen
reconstruct_manager_screen = reconstruct.reconstruct_manager_screen
remove_all_logs = cleaning_ops.remove_all_logs
rerun_last_tool = shell_tools.rerun_last_tool
job_status_poll_screen = shell_tools.job_status_poll_screen
run_tool_background_screen = job_control.run_tool_background_screen
stop_job_screen = job_control.stop_job_screen
pause_job_screen = job_control.pause_job_screen
resume_job_screen = job_control.resume_job_screen
residual_timeline_screen = logs_analysis.residual_timeline_screen
run_checkmesh = run.run_checkmesh
run_current_solver = solver.run_current_solver
run_current_solver_live = solver.run_current_solver_live
run_current_solver_parallel = solver.run_current_solver_parallel
run_shell_script_screen = shell_tools.run_shell_script_screen
renumber_mesh_screen = mesh_utils.renumber_mesh_screen
transform_points_screen = mesh_utils.transform_points_screen
cfmesh_screen = mesh_utils.cfmesh_screen
safe_stop_screen = solver_control.safe_stop_screen
sampling_sets_screen = postprocessing.sampling_sets_screen
postprocessing_browser_screen = postprocessing.postprocessing_browser_screen
solver_resurrection_screen = solver_control.solver_resurrection_screen
time_directory_pruner_screen = time_pruner.time_directory_pruner_screen
yplus_screen = yplus.yplus_screen


@dataclass
class _ToolAlias:
    handler: Callable[[], None]
    background_cmd: list[str] | None
    display_name: str


def run_tool_by_name(
    stdscr: Any,
    case_path: Path,
    name: str,
    *,
    background: bool = False,
) -> bool:
    resolved = _resolve_catalog_tool(case_path, name)
    if resolved is not None:
        display_name, command = resolved
        if background:
            job_control.start_tool_background(
                stdscr,
                case_path,
                _normalize_tool_name(display_name),
                command,
            )
            return True
        _run_simple_tool(stdscr, case_path, display_name, command)
        return True

    aliases = _tool_aliases(stdscr, case_path)
    key = _normalize_tool_name(name)
    alias = aliases.get(key)
    if alias is None:
        return False
    if background:
        if alias.background_cmd is None:
            _show_message(stdscr, f"{alias.display_name} cannot run in background.")
            return True
        job_control.start_tool_background(
            stdscr,
            case_path,
            alias.display_name,
            alias.background_cmd,
        )
        return True
    alias.handler()
    return True


def _resolve_catalog_tool(case_path: Path, name: str) -> tuple[str, list[str]] | None:
    resolved = run_ops.resolve_tool(case_path, name)
    if resolved is not None:
        return resolved
    normalized = _normalize_tool_name(name)
    if normalized.startswith("post:"):
        token = normalized.split(":", 1)[1]
        return run_ops.resolve_tool(case_path, f"[post] {token}")
    if normalized.startswith("post."):
        token = normalized.split(".", 1)[1]
        return run_ops.resolve_tool(case_path, f"[post] {token}")
    return None


def _run_snappy_staged(stdscr: Any, case_path: Path) -> None:
    run_snappy = snappy_staged_screen(stdscr, case_path)
    if run_snappy:
        run_tool_by_name(stdscr, case_path, "snappyHexMesh")


_CASE_OP_LABELS = [
    "Preflight",
    "Case doctor",
    "Status",
    "Compare dictionaries",
    "Back",
]


def _case_operations_menu(
    stdscr: Any,
    *,
    command_handler: Callable[[str], str | None] | None,
    command_suggestions: Callable[[], list[str]] | None,
) -> int:
    menu = build_menu(
        stdscr,
        "Case operations",
        _CASE_OP_LABELS,
        menu_key="menu:case_ops",
        command_handler=command_handler,
        command_suggestions=command_suggestions,
    )
    return menu.navigate()


def _show_case_preflight(stdscr: Any, case_path: Path) -> None:
    try:
        payload = knife_ops.preflight_payload(case_path)
    except ValueError as exc:
        _show_message(stdscr, str(exc))
        return
    lines = [f"case={payload['case']}"]
    for key, value in payload["checks"].items():
        lines.append(f"{key}={'ok' if value else 'missing'}")
    if payload["solver_error"]:
        lines.append(f"solver_error={payload['solver_error']}")
    lines.append(f"ok={payload['ok']}")
    Viewer(stdscr, "\n".join(lines)).display()


def _show_case_status(stdscr: Any, case_path: Path) -> None:
    try:
        payload = knife_ops.status_payload(case_path)
    except ValueError as exc:
        _show_message(stdscr, str(exc))
        return
    lines = status_render_service.case_status_lines(payload)
    Viewer(stdscr, "\n".join(lines)).display()


def _compare_lines(payload: dict[str, Any]) -> list[str]:
    lines = [
        f"left_case={payload['left_case']}",
        f"right_case={payload['right_case']}",
        f"diff_count={payload['diff_count']}",
    ]
    for diff in payload["diffs"]:
        lines.append("")
        lines.append(diff["rel_path"])
        if diff["error"]:
            lines.append(f"  error: {diff['error']}")
        if diff["missing_in_left"]:
            lines.append(f"  missing_in_left: {', '.join(diff['missing_in_left'])}")
        if diff["missing_in_right"]:
            lines.append(f"  missing_in_right: {', '.join(diff['missing_in_right'])}")
        for row in diff.get("value_diffs", [])[:20]:
            lines.append(f"  {row['key']}: left={row['left']} right={row['right']}")
        if len(diff.get("value_diffs", [])) > 20:
            lines.append(f"  value_diff_more={len(diff['value_diffs']) - 20}")
    return lines


def _show_case_compare(stdscr: Any, case_path: Path) -> None:
    other = prompt_line(stdscr, "Compare with case path: ")
    if not other:
        return
    try:
        payload = knife_ops.compare_payload(case_path, Path(other))
    except ValueError as exc:
        _show_message(stdscr, str(exc))
        return
    Viewer(stdscr, "\n".join(_compare_lines(payload))).display()


def case_operations_screen(
    stdscr: Any,
    case_path: Path,
    *,
    command_handler: Callable[[str], str | None] | None = None,
    command_suggestions: Callable[[], list[str]] | None = None,
) -> None:
    while True:
        choice = _case_operations_menu(
            stdscr,
            command_handler=command_handler,
            command_suggestions=command_suggestions,
        )
        if choice in (-1, len(_CASE_OP_LABELS) - 1):
            return
        if choice == 0:
            _show_case_preflight(stdscr, case_path)
            continue
        if choice == 1:
            case_doctor.case_doctor_screen(stdscr, case_path)
            continue
        if choice == 2:
            _show_case_status(stdscr, case_path)
            continue
        _show_case_compare(stdscr, case_path)


def _tool_aliases(stdscr: Any, case_path: Path) -> dict[str, _ToolAlias]:
    aliases: dict[str, _ToolAlias] = {}

    def add(
        name: str,
        handler: Callable[[], None],
        background_cmd: list[str] | None = None,
    ) -> None:
        key = _normalize_tool_name(name)
        existing = aliases.get(key)
        if existing and background_cmd is None:
            background_cmd = existing.background_cmd
        aliases[key] = _ToolAlias(handler=handler, background_cmd=background_cmd, display_name=name)

    def add_many(
        names: tuple[str, ...],
        handler: Callable[[], None],
        background_cmd: list[str] | None = None,
    ) -> None:
        for name in names:
            add(name, handler, background_cmd)

    def bind(func: Callable[[Any, Path], None]) -> Callable[[], None]:
        return partial(func, stdscr, case_path)

    handlers: dict[str, Callable[[], None]] = {
        "rerun": bind(rerun_last_tool),
        "highspeed": bind(high_speed_helper_screen),
        "boundarymatrix": bind(boundary_matrix_screen),
        "initialconditions": bind(initial_conditions_screen),
        "thermowizard": bind(thermophysical_wizard_screen),
        "blockmeshhelper": bind(blockmesh_helper_screen),
        "snappystaged": bind(_run_snappy_staged),
        "pipelineedit": bind(pipeline_editor_screen),
        "pipelinerun": bind(pipeline_runner_screen),
        "parametricwizard": bind(foamlib_parametric_study_screen),
        "fieldsummary": bind(field_summary_screen),
        "postprocessingbrowser": bind(postprocessing_browser_screen),
        "samplingsets": bind(sampling_sets_screen),
        "runparallel": bind(run_current_solver_parallel),
        "meshquality": bind(run_checkmesh),
        "physicshelpers": bind(physics_tools_screen),
        "runscript": bind(run_shell_script_screen),
        "postprocess": bind(post_process_prompt),
        "foamcalc": bind(foam_calc_prompt),
        "runcurrentsolver": bind(run_current_solver),
        "runlive": bind(run_current_solver_live),
        "removelogs": bind(remove_all_logs),
        "cleantimedirs": bind(clean_time_directories),
        "reconstruct_manager": bind(reconstruct_manager_screen),
        "timedir_pruner": bind(time_directory_pruner_screen),
        "safestop": bind(safe_stop_screen),
        "solveresume": bind(solver_resurrection_screen),
        "clone": bind(clone_case),
        "yplus": bind(yplus_screen),
        "logs": bind(logs_screen),
        "residuals": bind(residual_timeline_screen),
        "probes": bind(probes_viewer_screen),
        "loganalysis": bind(log_analysis_screen),
        "paraview": bind(open_paraview_screen),
        "diagnostics": bind(diagnostics_screen),
        "casedoctor": bind(case_doctor.case_doctor_screen),
        "jobstatus": bind(job_status_poll_screen),
        "jobstart": bind(run_tool_background_screen),
        "jobstop": bind(stop_job_screen),
        "jobpause": bind(pause_job_screen),
        "jobresume": bind(resume_job_screen),
        "clitools": bind(case_operations_screen),
        "knife": bind(case_operations_screen),
        "plot": bind(residual_timeline_screen),
        "watch": bind(job_status_poll_screen),
        "run": bind(run_current_solver),
        "renumbermesh": bind(renumber_mesh_screen),
        "transformpoints": bind(transform_points_screen),
        "cfmesh": bind(cfmesh_screen),
    }
    for names in STATIC_TOOL_ALIAS_GROUPS:
        add_many(names, handlers[names[0]])

    return aliases


TOOLS_SPECIAL_HINTS = [
    "Environment and installation checks",
    "Case doctor checks required files, mesh, and syntax",
    "Case operations: preflight, doctor, status, compare",
    "Run a shell script from case folder",
    "Clone case directory and clean mesh/time/logs",
    "View tracked solver jobs (no external tools)",
    "Stop a running job (tracked jobs)",
    "Physics helpers (high-speed, yPlus)",
]


def tools_screen(  # noqa: C901
    stdscr: Any,
    case_path: Path,
    *,
    command_handler: Callable[[str], str | None] | None = None,
    command_suggestions: Callable[[], list[str]] | None = None,
) -> None:
    """
    Tools menu with common solvers/utilities, job helpers, logs, and
    optional shell scripts, all in a single flat list.
    """
    base_tools: list[tuple[str, list[str]]] = []
    extra_tools = load_tool_presets(case_path)
    post_tools = [
        (f"[post] {name}", cmd) for name, cmd in load_postprocessing_presets(case_path)
    ]

    simple_tools = base_tools + extra_tools + post_tools

    labels = ["Re-run last tool"] + [name for name, _ in simple_tools] + [
        "Diagnostics",
        "Case doctor",
        "Case operations",
        "Run shell script",
        "Clone case",
        "Job status",
        "Stop job",
        "Physics helpers",
    ]

    def hint_for(idx: int) -> str:
        if idx == 0:
            last = get_last_tool_run()
            if last is None:
                base = "Re-run last tool (none yet)"
            else:
                base = f"Re-run last tool: {last.name}"
            return f"{base} | {tool_status_mode()}"
        simple_index = idx - 1
        if 0 <= simple_index < len(simple_tools):
            name, _cmd = simple_tools[simple_index]
            if name.startswith("[post]"):
                return f"Post-processing preset: {name} | {tool_status_mode()}"
            return f"Run tool: {name} | {tool_status_mode()}"
        special = idx - 1 - len(simple_tools)
        if 0 <= special < len(TOOLS_SPECIAL_HINTS):
            label = labels[idx]
            base = menu_hint("menu:tools", label) or TOOLS_SPECIAL_HINTS[special]
            return f"{base} | {tool_status_mode()}"
        label = labels[idx] if 0 <= idx < len(labels) else ""
        return menu_hint("menu:tools", label)

    disabled = set(range(len(labels))) if _no_foam_active() else None
    status_line = (
        "Limited mode: OpenFOAM env not found (simple editor only)"
        if _no_foam_active()
        else None
    )

    while True:
        last_status = last_tool_status_line()
        status = (
            f"{status_line} | {last_status}"
            if status_line and last_status
            else last_status or status_line
        )
        menu = build_menu(
            stdscr,
            "Tools",
            [*labels, "Back"],
            menu_key="menu:tools",
            hint_provider=hint_for,
            status_line=status,
            disabled_indices=disabled,
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            help_lines=tools_help(),
        )
        choice = menu.navigate()
        if choice in (-1, len(labels)):
            return

        simple_index = choice - 1
        if 0 <= simple_index < len(simple_tools):
            name, cmd = simple_tools[simple_index]
            _run_simple_tool(stdscr, case_path, name, cmd)
            continue

        special_index = choice - 1 - len(simple_tools)
        if special_index == 0:
            diagnostics_screen(
                stdscr,
                case_path,
                command_handler=command_handler,
                command_suggestions=command_suggestions,
            )
        elif special_index == 1:
            case_doctor.case_doctor_screen(stdscr, case_path)
        elif special_index == 2:
            case_operations_screen(
                stdscr,
                case_path,
                command_handler=command_handler,
                command_suggestions=command_suggestions,
            )
        elif special_index == 3:
            run_shell_script_screen(stdscr, case_path)
        elif special_index == 4:
            clone_case(stdscr, case_path)
        elif special_index == 5:
            job_status_poll_screen(stdscr, case_path)
        elif special_index == 6:
            stop_job_screen(stdscr, case_path)
        elif special_index == 7:
            physics_tools_screen(
                stdscr,
                case_path,
                command_handler=command_handler,
                command_suggestions=command_suggestions,
            )


def physics_tools_screen(
    stdscr: Any,
    case_path: Path,
    *,
    command_handler: Callable[[str], str | None] | None = None,
    command_suggestions: Callable[[], list[str]] | None = None,
) -> None:
    options = [
        "High-speed helper",
        "yPlus estimator",
        "Back",
    ]
    disabled = {1} if _no_foam_active() else set()
    while True:
        menu = build_menu(
            stdscr,
            "Tools: Physics",
            options,
            menu_key="menu:tools_physics",
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            disabled_indices=disabled,
            help_lines=tools_physics_help(),
        )
        choice = menu.navigate()
        if choice in (-1, len(options) - 1):
            return
        if choice == 0:
            high_speed_helper_screen(stdscr, case_path)
        elif choice == 1:
            yplus_screen(stdscr, case_path)
