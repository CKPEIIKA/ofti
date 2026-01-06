import curses
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .editor import Viewer
from .menus import Menu
from .openfoam import read_entry, OpenFOAMError


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    stdscr.addstr("Press any key to continue.\n")
    stdscr.refresh()
    stdscr.getch()


def load_tool_presets(case_path: Path) -> list[tuple[str, list[str]]]:
    """
    Load extra tools from an optional per-case file `of_tui.tools`.

    Format (one per line, lines starting with # are ignored):
      name: command with args
    Example:
      simpleFoam: simpleFoam -case .
    """
    presets: list[tuple[str, list[str]]] = []
    cfg_path = case_path / "of_tui.tools"
    if not cfg_path.is_file():
        return presets

    try:
        for raw_line in cfg_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            name, cmd_str = line.split(":", 1)
            name = name.strip()
            cmd_str = cmd_str.strip()
            if not name or not cmd_str:
                continue
            try:
                cmd = shlex.split(cmd_str)
            except ValueError:
                continue
            presets.append((name, cmd))
    except OSError:
        return presets

    return presets


def load_postprocessing_presets(case_path: Path) -> list[tuple[str, list[str]]]:
    """
    Load optional post-processing commands from `of_tui.postprocessing`.
    Same format as `of_tui.tools`.
    """
    presets: list[tuple[str, list[str]]] = []
    cfg_path = case_path / "of_tui.postprocessing"
    if not cfg_path.is_file():
        return presets

    try:
        for raw_line in cfg_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            name, cmd_str = line.split(":", 1)
            name = name.strip()
            cmd_str = cmd_str.strip()
            if not name or not cmd_str:
                continue
            try:
                cmd = shlex.split(cmd_str)
            except ValueError:
                continue
            presets.append((name, cmd))
    except OSError:
        return presets

    return presets


def _run_simple_tool(stdscr: Any, case_path: Path, name: str, cmd: list[str]) -> None:
    expanded = _expand_command(cmd, case_path)
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if wm_dir:
        cmd_str = " ".join(shlex.quote(part) for part in expanded)
        shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; runApplication {cmd_str}'
        _run_shell_tool(stdscr, case_path, name, shell_cmd)
        return

    try:
        result = subprocess.run(
            expanded,
            cwd=case_path,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        _show_message(stdscr, f"Failed to run {name}: {exc}")
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    summary_lines = [
        f"$ cd {case_path}",
        f"$ {' '.join(cmd)}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
        "stdout:",
        result.stdout or "(empty)",
        "",
        "stderr:",
        result.stderr or "(empty)",
    ]
    viewer = Viewer(stdscr, "\n".join(summary_lines))
    viewer.display()


def _run_shell_tool(stdscr: Any, case_path: Path, name: str, shell_cmd: str) -> None:
    shell_cmd = _expand_shell_command(shell_cmd, case_path)
    try:
        result = subprocess.run(
            ["bash", "-lc", shell_cmd],
            cwd=case_path,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        _show_message(stdscr, f"Failed to run {name}: {exc}")
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    summary_lines = [
        f"$ cd {case_path}",
        f"$ bash -lc {shell_cmd}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
        "stdout:",
        result.stdout or "(empty)",
        "",
        "stderr:",
        result.stderr or "(empty)",
    ]
    viewer = Viewer(stdscr, "\n".join(summary_lines))
    viewer.display()


def tools_screen(stdscr: Any, case_path: Path) -> None:
    """
    Tools menu with common solvers/utilities, job helpers, logs, and
    optional shell scripts, all in a single flat list.
    """
    base_tools = [
        ("blockMesh", ["blockMesh"]),
        ("decomposePar", ["decomposePar"]),
        ("reconstructPar", ["reconstructPar"]),
        ("foamListTimes", ["foamListTimes"]),
    ]
    extra_tools = load_tool_presets(case_path)
    job_tools = [
        ("foamCheckJobs", ["foamCheckJobs"]),
        ("foamPrintJobs", ["foamPrintJobs"]),
    ]
    post_tools = [
        (f"[post] {name}", cmd) for name, cmd in load_postprocessing_presets(case_path)
    ]

    simple_tools = base_tools + extra_tools + job_tools + post_tools

    labels = [name for name, _ in simple_tools] + [
        "foamJob (run job)",
        "foamEndJob (stop job)",
        "Run .sh script",
        "foamDictionary (prompt)",
        "postProcess (prompt)",
        "foamCalc (prompt)",
        "Run current solver (runApplication)",
        "Remove all logs (CleanFunctions)",
        "Clean time directories (CleanFunctions)",
        "Clean case (CleanFunctions)",
    ]
    menu = Menu(stdscr, "Tools", labels + ["Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    # Simple tools segment.
    if choice < len(simple_tools):
        name, cmd = simple_tools[choice]
        _run_simple_tool(stdscr, case_path, name, cmd)
        return

    # Offsets into special actions.
    special_index = choice - len(simple_tools)
    if special_index == 0:
        foam_job_prompt(stdscr, case_path)
    elif special_index == 1:
        foam_end_job_prompt(stdscr, case_path)
    elif special_index == 2:
        run_shell_script_screen(stdscr, case_path)
    elif special_index == 3:
        foam_dictionary_prompt(stdscr, case_path)
    elif special_index == 4:
        post_process_prompt(stdscr, case_path)
    elif special_index == 5:
        foam_calc_prompt(stdscr, case_path)
    elif special_index == 6:
        run_current_solver(stdscr, case_path)
    elif special_index == 7:
        remove_all_logs(stdscr, case_path)
    elif special_index == 8:
        clean_time_directories(stdscr, case_path)
    elif special_index == 9:
        clean_case(stdscr, case_path)


def logs_screen(stdscr: Any, case_path: Path) -> None:
    """
    Simple log viewer for files matching log.* in the case directory.
    """
    log_files = sorted(case_path.glob("log.*"))
    if not log_files:
        _show_message(stdscr, "No log.* files found in case directory.")
        return

    labels = [p.name for p in log_files]
    menu = Menu(stdscr, "Select log file", labels + ["Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    path = log_files[choice]

    # After choosing a log file, offer full view or tail view.
    options = ["View full log", "View last 100 lines"]
    sub = Menu(stdscr, f"Log: {path.name}", options + ["Back"])
    sub_choice = sub.navigate()
    if sub_choice == -1 or sub_choice == len(options):
        return

    tail = sub_choice == 1
    try:
        text = path.read_text()
    except OSError as exc:
        _show_message(stdscr, f"Failed to read {path.name}: {exc}")
        return

    if tail:
        lines = text.splitlines()
        text = "\n".join(lines[-100:]) if lines else "(empty)"

    viewer = Viewer(stdscr, text)
    viewer.display()


def run_shell_script_screen(stdscr: Any, case_path: Path) -> None:
    """
    Discover and run *.sh scripts in the case directory.

    Scripts are executed with the case directory as the current working
    directory, and their output is captured and shown in a viewer.
    """
    scripts = sorted(p for p in case_path.glob("*.sh") if p.is_file())
    if not scripts:
        _show_message(stdscr, "No *.sh scripts found in case directory.")
        return

    labels = [p.name for p in scripts]
    menu = Menu(stdscr, "Select script to run", labels + ["Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    path = scripts[choice]
    try:
        result = subprocess.run(
            ["sh", str(path)],
            cwd=case_path,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        _show_message(stdscr, f"Failed to run {path.name}: {exc}")
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    lines = [
        f"$ cd {case_path}",
        f"$ sh {path.name}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
        "stdout:",
        result.stdout or "(empty)",
        "",
        "stderr:",
        result.stderr or "(empty)",
    ]
    viewer = Viewer(stdscr, "\n".join(lines))
    viewer.display()


def foam_dictionary_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for a dictionary file and optional arguments to pass to foamDictionary.
    """
    curses.echo()
    stdscr.clear()
    stdscr.addstr("Relative path to dictionary (default system/controlDict): ")
    stdscr.refresh()
    path_input = stdscr.getstr().decode().strip()
    if not path_input:
        path_input = "system/controlDict"

    dictionary_path = (case_path / path_input).resolve()
    if not dictionary_path.is_file():
        curses.noecho()
        _show_message(stdscr, f"{dictionary_path} not found.")
        return

    stdscr.addstr("foamDictionary args (e.g. -entry application): ")
    stdscr.refresh()
    args_line = stdscr.getstr().decode().strip()
    curses.noecho()

    try:
        args = shlex.split(args_line) if args_line else []
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["foamDictionary", str(dictionary_path), *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=case_path,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        _show_message(stdscr, f"Failed to run foamDictionary: {exc}")
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    lines = [
        f"$ cd {case_path}",
        f"$ {' '.join(cmd)}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
        "stdout:",
        result.stdout or "(empty)",
        "",
        "stderr:",
        result.stderr or "(empty)",
    ]
    viewer = Viewer(stdscr, "\n".join(lines))
    viewer.display()


def post_process_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for postProcess arguments, suggesting use of latestTime.
    """
    latest = _latest_time(case_path)
    curses.echo()
    stdscr.clear()
    stdscr.addstr("postProcess args (e.g. -latestTime -funcs '(mag(U))'):\n")
    stdscr.addstr(f"Tip: latest time detected = {latest}\n")
    stdscr.addstr("> ")
    stdscr.refresh()
    args_line = stdscr.getstr().decode().strip()
    curses.noecho()

    try:
        args = shlex.split(args_line) if args_line else ["-latestTime"]
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["postProcess", *args]
    _run_simple_tool(stdscr, case_path, "postProcess", cmd)


def foam_calc_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for foamCalc arguments with helpers.
    """
    latest = _latest_time(case_path)
    curses.echo()
    stdscr.clear()
    stdscr.addstr("foamCalc args (e.g. components U -latestTime):\n")
    stdscr.addstr(f"Tip: latest time detected = {latest}\n")
    stdscr.addstr("> ")
    stdscr.refresh()
    args_line = stdscr.getstr().decode().strip()
    curses.noecho()

    if not args_line:
        _show_message(stdscr, "No arguments provided for foamCalc.")
        return

    try:
        args = shlex.split(args_line)
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["foamCalc", *args]
    _run_simple_tool(stdscr, case_path, "foamCalc", cmd)


def _require_wm_project_dir(stdscr: Any) -> str | None:
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if not wm_dir:
        _show_message(
            stdscr,
            "WM_PROJECT_DIR is not set. Please source your OpenFOAM environment first.",
        )
        return None
    return wm_dir


def run_current_solver(stdscr: Any, case_path: Path) -> None:
    """
    Determine the solver from system/controlDict and run it via
    runApplication (RunFunctions).
    """
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        _show_message(stdscr, "system/controlDict not found in case directory.")
        return

    try:
        value = read_entry(control_dict, "application")
    except OpenFOAMError as exc:
        _show_message(stdscr, f"Failed to read application: {exc}")
        return

    solver_line = value.strip()
    if not solver_line:
        _show_message(stdscr, "application entry is empty.")
        return

    solver = solver_line.split()[0].rstrip(";")
    if not solver:
        _show_message(stdscr, "Could not determine solver from application entry.")
        return

    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir is None:
        return

    shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; runApplication {shlex.quote(solver)}'
    _run_shell_tool(stdscr, case_path, f"runApplication {solver}", shell_cmd)


def remove_all_logs(stdscr: Any, case_path: Path) -> None:
    """
    Remove log.* files using CleanFunctions helpers.
    """
    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir is None:
        return

    shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanApplicationLogs'
    _run_shell_tool(stdscr, case_path, "cleanApplicationLogs", shell_cmd)


def clean_time_directories(stdscr: Any, case_path: Path) -> None:
    """
    Remove time directories using CleanFunctions.
    """
    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir is None:
        return

    shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanTimeDirectories'
    _run_shell_tool(stdscr, case_path, "cleanTimeDirectories", shell_cmd)


def clean_case(stdscr: Any, case_path: Path) -> None:
    """
    Run CleanFunctions cleanCase to remove logs, time directories, etc.
    """
    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir is None:
        return

    shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanCase'
    _run_shell_tool(stdscr, case_path, "cleanCase", shell_cmd)


def _expand_command(cmd: list[str], case_path: Path) -> list[str]:
    latest = _latest_time(case_path)
    return [part.replace("{{latestTime}}", latest) for part in cmd]


def _expand_shell_command(shell_cmd: str, case_path: Path) -> str:
    latest = _latest_time(case_path)
    return shell_cmd.replace("{{latestTime}}", latest)


def _latest_time(case_path: Path) -> str:
    latest_value = 0.0
    found = False
    for entry in case_path.iterdir():
        if not entry.is_dir():
            continue
        try:
            value = float(entry.name)
        except ValueError:
            continue
        if not found or value > latest_value:
            latest_value = value
            found = True
    return f"{latest_value:g}" if found else "0"


def foam_job_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for foamJob arguments and run it.
    """
    curses.echo()
    stdscr.clear()
    stdscr.addstr("foamJob arguments (e.g. simpleFoam -case .): ")
    stdscr.refresh()
    arg_line = stdscr.getstr().decode().strip()
    curses.noecho()

    if not arg_line:
        return

    try:
        args = shlex.split(arg_line)
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    try:
        result = subprocess.run(
            ["foamJob", *args],
            cwd=case_path,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        _show_message(stdscr, f"Failed to run foamJob: {exc}")
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    lines = [
        f"$ cd {case_path}",
        f"$ foamJob {' '.join(args)}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
        "stdout:",
        result.stdout or "(empty)",
        "",
        "stderr:",
        result.stderr or "(empty)",
    ]
    viewer = Viewer(stdscr, "\n".join(lines))
    viewer.display()


def foam_end_job_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for foamEndJob arguments and run it.
    """
    curses.echo()
    stdscr.clear()
    stdscr.addstr("foamEndJob arguments (e.g. simpleFoam): ")
    stdscr.refresh()
    arg_line = stdscr.getstr().decode().strip()
    curses.noecho()

    if not arg_line:
        return

    try:
        args = shlex.split(arg_line)
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    try:
        result = subprocess.run(
            ["foamEndJob", *args],
            cwd=case_path,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        _show_message(stdscr, f"Failed to run foamEndJob: {exc}")
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    lines = [
        f"$ cd {case_path}",
        f"$ foamEndJob {' '.join(args)}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
        "stdout:",
        result.stdout or "(empty)",
        "",
        "stderr:",
        result.stderr or "(empty)",
    ]
    viewer = Viewer(stdscr, "\n".join(lines))
    viewer.display()


def diagnostics_screen(stdscr: Any, case_path: Path) -> None:
    """
    System and case diagnostics based on common OpenFOAM tools.
    """
    tools = [
        ("foamSystemCheck", ["foamSystemCheck"]),
        ("foamInstallationTest", ["foamInstallationTest"]),
        ("checkMesh", ["checkMesh"]),
    ]
    labels = [name for name, _ in tools] + ["View logs"]
    menu = Menu(stdscr, "Diagnostics", labels + ["Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    if choice == len(tools):
        logs_screen(stdscr, case_path)
        return

    name, cmd = tools[choice]
    try:
        result = subprocess.run(
            cmd,
            cwd=case_path,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        _show_message(stdscr, f"Failed to run {name}: {exc}")
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    lines = [
        f"$ cd {case_path}",
        f"$ {' '.join(cmd)}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
        "stdout:",
        result.stdout or "(empty)",
        "",
        "stderr:",
        result.stderr or "(empty)",
    ]
    viewer = Viewer(stdscr, "\n".join(lines))
    viewer.display()
