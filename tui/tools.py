import curses
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .editor import Viewer
from .menus import Menu


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


def _run_simple_tool(stdscr: Any, case_path: Path, name: str, cmd: list[str]) -> None:
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

    simple_tools = base_tools + extra_tools + job_tools

    labels = [name for name, _ in simple_tools] + [
        "foamJob (run job)",
        "foamEndJob (stop job)",
        "View logs",
        "Run .sh script",
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
        logs_screen(stdscr, case_path)
    elif special_index == 3:
        run_shell_script_screen(stdscr, case_path)


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
    labels = [name for name, _ in tools]
    menu = Menu(stdscr, "Diagnostics", labels + ["Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
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
