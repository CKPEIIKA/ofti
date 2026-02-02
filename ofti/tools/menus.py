from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
    time_pruner,
    tool_dicts_foamcalc,
    tool_dicts_postprocess,
    yplus,
)
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
from ofti.ui_curses.blockmesh_helper import blockmesh_helper_screen
from ofti.ui_curses.boundary_matrix import boundary_matrix_screen
from ofti.ui_curses.help import menu_hint, tools_help, tools_physics_help
from ofti.ui_curses.high_speed import high_speed_helper_screen
from ofti.ui_curses.initial_conditions import initial_conditions_screen
from ofti.ui_curses.menus import Menu
from ofti.ui_curses.snappy_toggle import snappy_staged_screen
from ofti.ui_curses.thermo_wizard import thermophysical_wizard_screen

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
residual_timeline_screen = logs_analysis.residual_timeline_screen
run_checkmesh = run.run_checkmesh
run_current_solver = solver.run_current_solver
run_current_solver_live = solver.run_current_solver_live
run_current_solver_parallel = solver.run_current_solver_parallel
run_decomposepar = run.run_decomposepar
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


def _run_snappy_staged(stdscr: Any, case_path: Path) -> None:
    run_snappy = snappy_staged_screen(stdscr, case_path)
    if run_snappy:
        run_tool_by_name(stdscr, case_path, "snappyHexMesh")


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

    def run_simple(name: str, cmd: list[str]) -> Callable[[], None]:
        return lambda: _run_simple_tool(stdscr, case_path, name, list(cmd))

    base_tools = [
        ("blockMesh", ["blockMesh"]),
        ("snappyHexMesh", ["snappyHexMesh"]),
        ("decomposePar", ["decomposePar"]),
        ("reconstructPar", ["reconstructPar"]),
    ]
    extra_tools = load_tool_presets(case_path)
    post_tools = load_postprocessing_presets(case_path)

    for name, cmd in base_tools + extra_tools:
        add(name, run_simple(name, list(cmd)), background_cmd=list(cmd))

    for name, cmd in post_tools:
        add(name, run_simple(name, list(cmd)), background_cmd=list(cmd))
        add(f"post.{name}", run_simple(name, list(cmd)), background_cmd=list(cmd))
        add(f"post:{name}", run_simple(name, list(cmd)), background_cmd=list(cmd))
        add(f"post.{name}", run_simple(name, cmd))
        add(f"post:{name}", run_simple(name, cmd))

    add("rerun", lambda: rerun_last_tool(stdscr, case_path))
    add("last", lambda: rerun_last_tool(stdscr, case_path))
    add("highspeed", lambda: high_speed_helper_screen(stdscr, case_path))
    add("high_speed", lambda: high_speed_helper_screen(stdscr, case_path))
    add("highspeedhelper", lambda: high_speed_helper_screen(stdscr, case_path))
    add("boundarymatrix", lambda: boundary_matrix_screen(stdscr, case_path))
    add("boundary-matrix", lambda: boundary_matrix_screen(stdscr, case_path))
    add("initialconditions", lambda: initial_conditions_screen(stdscr, case_path))
    add("initial-conditions", lambda: initial_conditions_screen(stdscr, case_path))
    add("thermowizard", lambda: thermophysical_wizard_screen(stdscr, case_path))
    add("thermo-wizard", lambda: thermophysical_wizard_screen(stdscr, case_path))
    add("blockmeshhelper", lambda: blockmesh_helper_screen(stdscr, case_path))
    add("blockmesh-helper", lambda: blockmesh_helper_screen(stdscr, case_path))
    add(
        "snappystaged",
        lambda: _run_snappy_staged(stdscr, case_path),
    )
    add(
        "snappy-staged",
        lambda: _run_snappy_staged(stdscr, case_path),
    )
    add("pipelineedit", lambda: pipeline_editor_screen(stdscr, case_path))
    add("pipeline-edit", lambda: pipeline_editor_screen(stdscr, case_path))
    add("pipelinerun", lambda: pipeline_runner_screen(stdscr, case_path))
    add("pipeline-run", lambda: pipeline_runner_screen(stdscr, case_path))
    add("parametricwizard", lambda: foamlib_parametric_study_screen(stdscr, case_path))
    add("parametric-wizard", lambda: foamlib_parametric_study_screen(stdscr, case_path))
    add("fieldsummary", lambda: field_summary_screen(stdscr, case_path))
    add("field-summary", lambda: field_summary_screen(stdscr, case_path))
    add(
        "postprocessingbrowser",
        lambda: postprocessing_browser_screen(stdscr, case_path),
    )
    add(
        "postprocessing-browser",
        lambda: postprocessing_browser_screen(stdscr, case_path),
    )
    add("samplingsets", lambda: sampling_sets_screen(stdscr, case_path))
    add("sampling-sets", lambda: sampling_sets_screen(stdscr, case_path))
    add("runparallel", lambda: run_current_solver_parallel(stdscr, case_path))
    add("run-parallel", lambda: run_current_solver_parallel(stdscr, case_path))
    add("meshquality", lambda: run_checkmesh(stdscr, case_path))
    add("mesh-quality", lambda: run_checkmesh(stdscr, case_path))
    add("physicshelpers", lambda: physics_tools_screen(stdscr, case_path))
    add("physics-helpers", lambda: physics_tools_screen(stdscr, case_path))
    add("runscript", lambda: run_shell_script_screen(stdscr, case_path))
    add("postprocess", lambda: post_process_prompt(stdscr, case_path))
    add("foamcalc", lambda: foam_calc_prompt(stdscr, case_path))
    add("runcurrentsolver", lambda: run_current_solver(stdscr, case_path))
    add("runlive", lambda: run_current_solver_live(stdscr, case_path))
    add("removelogs", lambda: remove_all_logs(stdscr, case_path))
    add("cleantimedirs", lambda: clean_time_directories(stdscr, case_path))
    add("blockmesh", lambda: run.run_blockmesh(stdscr, case_path))
    add("decomposepar", lambda: run_decomposepar(stdscr, case_path))
    add("reconstruct_manager", lambda: reconstruct_manager_screen(stdscr, case_path))
    add("reconstructmanager", lambda: reconstruct_manager_screen(stdscr, case_path))
    add("timedir_pruner", lambda: time_directory_pruner_screen(stdscr, case_path))
    add("timedirpruner", lambda: time_directory_pruner_screen(stdscr, case_path))
    add("safestop", lambda: safe_stop_screen(stdscr, case_path))
    add("solveresume", lambda: solver_resurrection_screen(stdscr, case_path))
    add("clone", lambda: clone_case(stdscr, case_path))
    add("yplus", lambda: yplus_screen(stdscr, case_path))
    add("checkmesh", lambda: run_checkmesh(stdscr, case_path))
    add("logs", lambda: logs_screen(stdscr, case_path))
    add("viewlogs", lambda: logs_screen(stdscr, case_path))
    add("residuals", lambda: residual_timeline_screen(stdscr, case_path))
    add("residual_timeline", lambda: residual_timeline_screen(stdscr, case_path))
    add("probes", lambda: probes_viewer_screen(stdscr, case_path))
    add("probesviewer", lambda: probes_viewer_screen(stdscr, case_path))
    add("loganalysis", lambda: log_analysis_screen(stdscr, case_path))
    add("paraview", lambda: open_paraview_screen(stdscr, case_path))
    add("diagnostics", lambda: diagnostics_screen(stdscr, case_path))
    add("casedoctor", lambda: case_doctor.case_doctor_screen(stdscr, case_path))
    add("jobstatus", lambda: job_status_poll_screen(stdscr, case_path))
    add("jobstart", lambda: run_tool_background_screen(stdscr, case_path))
    add("jobstop", lambda: stop_job_screen(stdscr, case_path))
    add("renumbermesh", lambda: renumber_mesh_screen(stdscr, case_path))
    add("transformpoints", lambda: transform_points_screen(stdscr, case_path))
    add("cfmesh", lambda: cfmesh_screen(stdscr, case_path))
    add("sampling", lambda: sampling_sets_screen(stdscr, case_path))

    return aliases


TOOLS_SPECIAL_HINTS = [
    "Environment and installation checks",
    "Case doctor checks required files, mesh, and syntax",
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
        menu = Menu(
            stdscr,
            "Tools",
            [*labels, "Back"],
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
            run_shell_script_screen(stdscr, case_path)
        elif special_index == 3:
            clone_case(stdscr, case_path)
        elif special_index == 4:
            job_status_poll_screen(stdscr, case_path)
        elif special_index == 5:
            stop_job_screen(stdscr, case_path)
        elif special_index == 6:
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
        menu = Menu(
            stdscr,
            "Tools: Physics",
            options,
            disabled_indices=disabled,
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            hint_provider=lambda idx: menu_hint("menu:tools_physics", options[idx])
            if 0 <= idx < len(options)
            else "",
            help_lines=tools_physics_help(),
        )
        choice = menu.navigate()
        if choice in (-1, len(options) - 1):
            return
        if choice == 0:
            high_speed_helper_screen(stdscr, case_path)
        elif choice == 1:
            yplus_screen(stdscr, case_path)
