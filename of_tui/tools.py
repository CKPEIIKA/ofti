from __future__ import annotations

import curses
import os
import shlex
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union

from .editor import Viewer
from .menus import Menu
from .openfoam import read_entry, OpenFOAMError
from .config import get_config


@dataclass
class LastToolRun:
    name: str
    kind: str
    command: Union[list[str], str]


_LAST_TOOL_RUN: Optional[LastToolRun] = None


def _no_foam_hint() -> str:
    if os.environ.get("OF_TUI_NO_FOAM") == "1":
        return " (no-foam mode may prevent OpenFOAM tools from running)"
    return ""


def _with_no_foam_hint(message: str) -> str:
    hint = _no_foam_hint()
    return f"{message}{hint}" if hint else message


def _record_last_tool(name: str, kind: str, command: Union[list[str], str]) -> None:
    global _LAST_TOOL_RUN
    _LAST_TOOL_RUN = LastToolRun(name=name, kind=kind, command=command)


def tool_status_mode() -> str:
    mode = "no-foam" if os.environ.get("OF_TUI_NO_FOAM") == "1" else "foam"
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    suffix = f" ({wm_dir})" if wm_dir else ""
    return f"mode: {mode}{suffix}"


def _job_dir_hint() -> Optional[str]:
    job_dir = os.environ.get("FOAM_JOB_DIR", "~/.OpenFOAM/jobControl")
    path = Path(job_dir).expanduser()
    if path.is_dir():
        return None
    return f"hint: FOAM_JOB_DIR missing at {path}. Create it with: mkdir -p {path}"


def _maybe_job_hint(name: str) -> Optional[str]:
    if name in ("foamPrintJobs", "foamCheckJobs", "foamJob", "foamEndJob"):
        return _job_dir_hint()
    return None


def _load_presets_from_path(cfg_path: Path) -> list[tuple[str, list[str]]]:
    """
    Load tool presets from a colon-delimited config file.
    """
    presets: list[tuple[str, list[str]]] = []
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


def _normalize_tool_name(name: str) -> str:
    lowered = name.strip().lower()
    return "".join(ch for ch in lowered if ch.isalnum() or ch in ("-", "_", ".", ":"))


def list_tool_commands(case_path: Path) -> list[str]:
    return sorted(set(_tool_alias_keys(case_path)))


def run_tool_by_name(stdscr: Any, case_path: Path, name: str) -> bool:
    aliases = _tool_aliases(stdscr, case_path)
    key = _normalize_tool_name(name)
    handler = aliases.get(key)
    if handler is None:
        return False
    handler()
    return True


def _tool_aliases(stdscr: Any, case_path: Path) -> dict[str, Callable[[], None]]:
    aliases: dict[str, Callable[[], None]] = {}

    def add(name: str, handler: Callable[[], None]) -> None:
        aliases[_normalize_tool_name(name)] = handler

    def run_simple(name: str, cmd: list[str]) -> Callable[[], None]:
        return lambda: _run_simple_tool(stdscr, case_path, name, list(cmd))

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
    post_tools = load_postprocessing_presets(case_path)

    for name, cmd in base_tools + extra_tools + job_tools:
        add(name, run_simple(name, cmd))

    for name, cmd in post_tools:
        add(name, run_simple(name, cmd))
        add(f"post.{name}", run_simple(name, cmd))
        add(f"post:{name}", run_simple(name, cmd))

    add("rerun", lambda: rerun_last_tool(stdscr, case_path))
    add("last", lambda: rerun_last_tool(stdscr, case_path))
    add("foamjob", lambda: foam_job_prompt(stdscr, case_path))
    add("foamendjob", lambda: foam_end_job_prompt(stdscr, case_path))
    add("jobstatus", lambda: job_status_poll_screen(stdscr, case_path))
    add("job_status", lambda: job_status_poll_screen(stdscr, case_path))
    add("runscript", lambda: run_shell_script_screen(stdscr, case_path))
    add("foamdictionary", lambda: foam_dictionary_prompt(stdscr, case_path))
    add("postprocess", lambda: post_process_prompt(stdscr, case_path))
    add("foamcalc", lambda: foam_calc_prompt(stdscr, case_path))
    add("toposet", lambda: topo_set_prompt(stdscr, case_path))
    add("tool_dicts", lambda: tool_dicts_screen(stdscr, case_path))
    add("tooldicts", lambda: tool_dicts_screen(stdscr, case_path))
    add("runcurrentsolver", lambda: run_current_solver(stdscr, case_path))
    add("removelogs", lambda: remove_all_logs(stdscr, case_path))
    add("cleantimedirs", lambda: clean_time_directories(stdscr, case_path))
    add("cleancase", lambda: clean_case(stdscr, case_path))

    return aliases


def _tool_alias_keys(case_path: Path) -> list[str]:
    keys: list[str] = []

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
    post_tools = load_postprocessing_presets(case_path)

    for name, _ in base_tools + extra_tools + job_tools:
        keys.append(_normalize_tool_name(name))

    for name, _ in post_tools:
        keys.append(_normalize_tool_name(name))
        keys.append(_normalize_tool_name(f"post.{name}"))
        keys.append(_normalize_tool_name(f"post:{name}"))

    keys.extend(
        [
            _normalize_tool_name("rerun"),
            _normalize_tool_name("last"),
            _normalize_tool_name("foamJob"),
            _normalize_tool_name("foamEndJob"),
            _normalize_tool_name("runScript"),
            _normalize_tool_name("foamDictionary"),
            _normalize_tool_name("postProcess"),
            _normalize_tool_name("foamCalc"),
            _normalize_tool_name("topoSet"),
            _normalize_tool_name("tool_dicts"),
            _normalize_tool_name("toolDicts"),
            _normalize_tool_name("runCurrentSolver"),
            _normalize_tool_name("removeLogs"),
            _normalize_tool_name("cleanTimeDirs"),
            _normalize_tool_name("cleanCase"),
        ]
    )

    return keys


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
    cfg_path = case_path / "of_tui.tools"
    return _load_presets_from_path(cfg_path)


def load_postprocessing_presets(case_path: Path) -> list[tuple[str, list[str]]]:
    """
    Load optional post-processing commands from `of_tui.postprocessing`.
    Same format as `of_tui.tools`.
    """
    cfg_path = case_path / "of_tui.postprocessing"
    return _load_presets_from_path(cfg_path)


def _run_simple_tool(stdscr: Any, case_path: Path, name: str, cmd: list[str]) -> None:
    expanded = _expand_command(cmd, case_path)
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if wm_dir and get_config().use_runfunctions:
        cmd_str = " ".join(shlex.quote(part) for part in expanded)
        shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; runApplication {cmd_str}'
        _record_last_tool(name, "shell", shell_cmd)
        _run_shell_tool(stdscr, case_path, name, shell_cmd)
        return

    _record_last_tool(name, "simple", expanded)
    try:
        result = subprocess.run(
            expanded,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    summary_lines = [
        f"$ cd {case_path}",
        f"$ {' '.join(cmd)}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
    ]
    hint = _maybe_job_hint(name)
    if hint:
        summary_lines.append(hint)
        summary_lines.append("")
    summary_lines += [
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
    _record_last_tool(name, "shell", shell_cmd)
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    try:
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", shell_cmd],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    summary_lines = [
        f"$ cd {case_path}",
        f"$ bash --noprofile --norc -c {shell_cmd}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
    ]
    hint = _maybe_job_hint(name)
    if hint:
        summary_lines.append(hint)
        summary_lines.append("")
    summary_lines += [
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

    labels = ["Re-run last tool"] + [name for name, _ in simple_tools] + [
        "Job status (poll)",
        "foamJob (run job)",
        "foamEndJob (stop job)",
        "Run .sh script",
        "foamDictionary (prompt)",
        "postProcess (prompt)",
        "foamCalc (prompt)",
        "topoSet (prompt)",
        "Tool dicts (postProcess/topoSet/foamCalc)",
        "Run current solver (runApplication)",
        "Remove all logs (CleanFunctions)",
        "Clean time directories (CleanFunctions)",
        "Clean case (CleanFunctions)",
    ]

    def hint_for(idx: int) -> str:
        if idx == 0:
            if _LAST_TOOL_RUN is None:
                base = "Re-run last tool (none yet)"
            else:
                base = f"Re-run last tool: {_LAST_TOOL_RUN.name}"
            return f"{base} | {tool_status_mode()}"
        simple_index = idx - 1
        if 0 <= simple_index < len(simple_tools):
            name, _cmd = simple_tools[simple_index]
            if name.startswith("[post]"):
                return f"Post-processing preset: {name} | {tool_status_mode()}"
            return f"Run tool: {name} | {tool_status_mode()}"
        special = idx - 1 - len(simple_tools)
        hints = [
            "Poll foamCheckJobs/foamPrintJobs output",
            "Run foamJob with custom args",
            "Stop job via foamEndJob",
            "Run a shell script from case folder",
            "Run foamDictionary interactively",
            "Run postProcess with args (uses postProcessDict)",
            "Run foamCalc with args (uses foamCalcDict)",
            "Run topoSet with args (uses topoSetDict)",
            "Create/open tool dictionaries",
            "Run solver from system/controlDict",
            "Remove log.* files",
            "Remove time directories",
            "Clean case (logs + time dirs)",
        ]
        if 0 <= special < len(hints):
            return f"{hints[special]} | {tool_status_mode()}"
        return ""

    menu = Menu(stdscr, "Tools", labels + ["Back"], hint_provider=hint_for)
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    # Simple tools segment.
    if choice == 0:
        rerun_last_tool(stdscr, case_path)
        return
    simple_index = choice - 1
    if simple_index < len(simple_tools):
        name, cmd = simple_tools[simple_index]
        _run_simple_tool(stdscr, case_path, name, cmd)
        return

    # Offsets into special actions.
    special_index = choice - 1 - len(simple_tools)
    if special_index == 0:
        job_status_poll_screen(stdscr, case_path)
    elif special_index == 1:
        foam_job_prompt(stdscr, case_path)
    elif special_index == 2:
        foam_end_job_prompt(stdscr, case_path)
    elif special_index == 3:
        run_shell_script_screen(stdscr, case_path)
    elif special_index == 4:
        foam_dictionary_prompt(stdscr, case_path)
    elif special_index == 5:
        post_process_prompt(stdscr, case_path)
    elif special_index == 6:
        foam_calc_prompt(stdscr, case_path)
    elif special_index == 7:
        topo_set_prompt(stdscr, case_path)
    elif special_index == 8:
        tool_dicts_screen(stdscr, case_path)
    elif special_index == 9:
        run_current_solver(stdscr, case_path)
    elif special_index == 10:
        remove_all_logs(stdscr, case_path)
    elif special_index == 11:
        clean_time_directories(stdscr, case_path)
    elif special_index == 12:
        clean_case(stdscr, case_path)


def logs_screen(stdscr: Any, case_path: Path) -> None:
    """
    Simple log viewer for files matching log.* in the case directory.
    """
    while True:
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
        try:
            text = path.read_text()
        except OSError as exc:
            _show_message(stdscr, f"Failed to read {path.name}: {exc}")
            continue

        viewer = Viewer(stdscr, text)
        viewer.display()


def job_status_poll_screen(stdscr: Any, case_path: Path) -> None:
    """
    Poll foamCheckJobs/foamPrintJobs until the user quits.
    """
    stdscr.timeout(500)
    try:
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            header = "Job status (q to exit)"
            try:
                stdscr.addstr(header[: max(1, width - 1)] + "\n")
            except curses.error:
                pass

            hint = _maybe_job_hint("foamPrintJobs")
            if hint:
                try:
                    stdscr.addstr(hint[: max(1, width - 1)] + "\n\n")
                except curses.error:
                    pass
            else:
                try:
                    stdscr.addstr("\n")
                except curses.error:
                    pass

            output_lines: list[str] = []
            for tool in ("foamCheckJobs", "foamPrintJobs"):
                try:
                    result = subprocess.run(
                        [tool],
                        cwd=case_path,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except OSError as exc:
                    output_lines.append(f"{tool}: failed: {exc}")
                    continue
                output_lines.append(f"{tool} (exit {result.returncode})")
                output_lines.extend((result.stdout or "").splitlines())

            for line in output_lines:
                if stdscr.getyx()[0] >= height - 2:
                    break
                try:
                    stdscr.addstr(line[: max(1, width - 1)] + "\n")
                except curses.error:
                    break

            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), ord("Q")):
                return
    finally:
        stdscr.timeout(-1)


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
            check=False,
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


def rerun_last_tool(stdscr: Any, case_path: Path) -> None:
    if _LAST_TOOL_RUN is None:
        _show_message(stdscr, "No previous tool run recorded.")
        return

    last = _LAST_TOOL_RUN
    if last.kind == "shell":
        _run_shell_tool(stdscr, case_path, f"Re-run {last.name}", str(last.command))
    else:
        _run_simple_tool(stdscr, case_path, f"Re-run {last.name}", list(last.command))


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
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run foamDictionary: {exc}"))
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
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "postProcess",
        case_path / "system" / "postProcessDict",
        ["postProcess", "-list"],
    ):
        return
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
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "foamCalc",
        case_path / "system" / "foamCalcDict",
        ["foamCalc", "-help"],
    ):
        return
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


def topo_set_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for topoSet arguments.
    """
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "topoSet",
        case_path / "system" / "topoSetDict",
        ["topoSetDict"],
    ):
        return
    curses.echo()
    stdscr.clear()
    stdscr.addstr("topoSet args (press Enter to run with defaults):\n")
    stdscr.addstr("> ")
    stdscr.refresh()
    args_line = stdscr.getstr().decode().strip()
    curses.noecho()

    try:
        args = shlex.split(args_line) if args_line else []
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["topoSet", *args]
    _run_simple_tool(stdscr, case_path, "topoSet", cmd)


def _require_wm_project_dir(stdscr: Any) -> Optional[str]:
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if not wm_dir:
        _show_message(
            stdscr,
            _with_no_foam_hint(
                "WM_PROJECT_DIR is not set. Please source your OpenFOAM environment first."
            ),
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
        _show_message(stdscr, _with_no_foam_hint(f"Failed to read application: {exc}"))
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
    if wm_dir and get_config().use_runfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; runApplication {shlex.quote(solver)}'
        _run_shell_tool(stdscr, case_path, f"runApplication {solver}", shell_cmd)
        return

    _run_simple_tool(stdscr, case_path, solver, [solver])


def remove_all_logs(stdscr: Any, case_path: Path) -> None:
    """
    Remove log.* files using CleanFunctions helpers.
    """
    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir and get_config().use_cleanfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanApplicationLogs'
        _run_shell_tool(stdscr, case_path, "cleanApplicationLogs", shell_cmd)
        return

    removed = 0
    for path in case_path.glob("log.*"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    _show_message(stdscr, f"Removed {removed} log files.")


def clean_time_directories(stdscr: Any, case_path: Path) -> None:
    """
    Remove time directories using CleanFunctions.
    """
    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir and get_config().use_cleanfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanTimeDirectories'
        _run_shell_tool(stdscr, case_path, "cleanTimeDirectories", shell_cmd)
        return

    removed = 0
    for entry in case_path.iterdir():
        if not entry.is_dir():
            continue
        try:
            value = float(entry.name)
        except ValueError:
            continue
        if value < 0:
            continue
        try:
            for child in entry.rglob("*"):
                if child.is_file():
                    child.unlink()
            entry.rmdir()
            removed += 1
        except OSError:
            continue
    _show_message(stdscr, f"Removed {removed} time directories.")


def clean_case(stdscr: Any, case_path: Path) -> None:
    """
    Run CleanFunctions cleanCase to remove logs, time directories, etc.
    """
    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir and get_config().use_cleanfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanCase'
        _run_shell_tool(stdscr, case_path, "cleanCase", shell_cmd)
        return

    remove_all_logs(stdscr, case_path)
    clean_time_directories(stdscr, case_path)


def _expand_command(cmd: list[str], case_path: Path) -> list[str]:
    latest = _latest_time(case_path)
    return [part.replace("{{latestTime}}", latest) for part in cmd]


def _expand_shell_command(shell_cmd: str, case_path: Path) -> str:
    latest = _latest_time(case_path)
    return shell_cmd.replace("{{latestTime}}", latest)


def _latest_time(case_path: Path) -> str:
    try:
        result = subprocess.run(
            ["foamListTimes", "-latestTime"],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        result = None
    if result is not None and result.returncode == 0:
        value = (result.stdout or "").strip()
        if value:
            return value
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


def tool_dicts_screen(stdscr: Any, case_path: Path) -> None:
    items = [
        ("postProcess", case_path / "system" / "postProcessDict", ["postProcess", "-list"]),
        ("foamCalc", case_path / "system" / "foamCalcDict", ["foamCalc", "-help"]),
        ("topoSet", case_path / "system" / "topoSetDict", ["topoSetDict"]),
    ]
    labels = [f"{name}: {path.relative_to(case_path)}" for name, path, _ in items]
    menu = Menu(stdscr, "Tool dictionaries", labels + ["Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    name, path, helper_cmd = items[choice]
    if not _ensure_tool_dict(stdscr, case_path, name, path, helper_cmd):
        return
    _open_dict_preview(stdscr, path)


def _ensure_tool_dict(
    stdscr: Any,
    case_path: Path,
    name: str,
    path: Path,
    helper_cmd: Optional[list[str]],
) -> bool:
    if path.is_file():
        return True

    stdscr.clear()
    stdscr.addstr(f"{path.relative_to(case_path)} is missing.\n")
    stdscr.addstr("Provide a dictionary to continue.\n")
    stdscr.addstr("Generate template now? (y/N): ")
    stdscr.refresh()
    ch = stdscr.getch()
    if ch not in (ord("y"), ord("Y")):
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    generated = _generate_tool_dict_with_helper(case_path, helper_cmd, path)
    if not generated:
        _write_stub_dict(path, name)
    return True


def _generate_tool_dict_with_helper(
    case_path: Path, helper_cmd: Optional[list[str]], path: Path
) -> bool:
    if not helper_cmd:
        return False
    try:
        result = subprocess.run(
            helper_cmd,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    output = (result.stdout or "").strip()
    if result.returncode == 0 and output and "FoamFile" in output:
        try:
            path.write_text(output + "\n")
        except OSError:
            return False
        return True
    return False


def _write_stub_dict(path: Path, tool_name: str) -> None:
    template = [
        "/*--------------------------------*- C++ -*----------------------------------*\\",
        f"| OpenFOAM {tool_name} dictionary (stub)                           |",
        "\\*---------------------------------------------------------------------------*/",
        "FoamFile",
        "{",
        "    version     2.0;",
        "    format      ascii;",
        "    class       dictionary;",
        f"    object      {path.name};",
        "}",
        "",
        "// TODO: fill in tool configuration.",
        "",
    ]
    path.write_text("\n".join(template))


def _open_dict_preview(stdscr: Any, path: Path) -> None:
    try:
        content = path.read_text()
    except OSError as exc:
        _show_message(stdscr, f"Failed to read {path.name}: {exc}")
        return
    viewer = Viewer(stdscr, content)
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
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run foamJob: {exc}"))
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    lines = [
        f"$ cd {case_path}",
        f"$ foamJob {' '.join(args)}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
    ]
    hint = _maybe_job_hint("foamJob")
    if hint:
        lines.append(hint)
        lines.append("")
    lines += [
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
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run foamEndJob: {exc}"))
        return

    status = "OK" if result.returncode == 0 else "ERROR"
    lines = [
        f"$ cd {case_path}",
        f"$ foamEndJob {' '.join(args)}",
        "",
        f"status: {status} (exit code {result.returncode})",
        "",
    ]
    hint = _maybe_job_hint("foamEndJob")
    if hint:
        lines.append(hint)
        lines.append("")
    lines += [
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
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return

    _write_tool_log(case_path, name, result.stdout, result.stderr)

    if name == "checkMesh":
        _show_checkmesh_summary(stdscr, result.stdout, result.stderr)
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


def _write_tool_log(case_path: Path, name: str, stdout: str, stderr: str) -> None:
    if not stdout and not stderr:
        return
    log_path = case_path / f"log.{name}"
    content = "\n".join(
        [
            f"tool: {name}",
            "",
            "stdout:",
            stdout or "(empty)",
            "",
            "stderr:",
            stderr or "(empty)",
            "",
        ]
    )
    try:
        log_path.write_text(content)
    except OSError:
        pass


def _show_checkmesh_summary(stdscr: Any, stdout: str, stderr: str) -> None:
    output = stdout or ""
    summary = _format_checkmesh_summary(output)
    stdscr.clear()
    stdscr.addstr(summary + "\n")
    stdscr.addstr("Press r for raw output, any other key to return.\n")
    stdscr.refresh()
    ch = stdscr.getch()
    if ch in (ord("r"), ord("R")):
        lines = [
            "checkMesh raw output",
            "",
            "stdout:",
            stdout or "(empty)",
            "",
            "stderr:",
            stderr or "(empty)",
        ]
        Viewer(stdscr, "\n".join(lines)).display()


def _format_checkmesh_summary(output: str) -> str:
    cells = _match_first(
        output,
        [
            r"(?i)number of cells\\s*:\\s*(\\d+)",
            r"(?i)cells\\s*:\\s*(\\d+)",
        ],
    )
    non_ortho = _match_first(
        output,
        [r"(?i)max\\s+non-orthogonality\\s*=\\s*([0-9eE.+-]+)"],
    )
    skew = _match_first(output, [r"(?i)max\\s+skewness\\s*=\\s*([0-9eE.+-]+)"])
    failed = _match_first(output, [r"(?i)failed\\s+(\\d+)\\s+mesh checks"])
    mesh_ok = "mesh ok" in output.lower()

    errors = "0" if mesh_ok and not failed else failed or "1"
    status = "OK" if mesh_ok and errors == "0" else "FAIL"

    rows = [
        ("Cells", cells or "unknown"),
        ("Max non-orth", non_ortho or "unknown"),
        ("Max skewness", skew or "unknown"),
        ("Errors", errors),
        ("Status", status),
    ]
    return _ascii_kv_table("checkMesh summary", rows)


def _match_first(text: str, patterns: list[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _ascii_kv_table(title: str, rows: list[tuple[str, str]]) -> str:
    if not rows:
        return title
    left_width = max(len(label) for label, _value in rows)
    right_width = max(len(value) for _label, value in rows)
    header_width = max(len(title), left_width + right_width + 3)
    left_width = max(left_width, header_width - right_width - 3)

    top = "+" + "-" * (left_width + 2) + "+" + "-" * (right_width + 2) + "+"
    lines = [top]
    lines.append(
        f"| {title.ljust(left_width + right_width + 1)} |".ljust(
            left_width + right_width + 5
        )
    )
    lines.append(top)
    for label, value in rows:
        lines.append(f"| {label.ljust(left_width)} | {value.ljust(right_width)} |")
    lines.append(top)
    return "\\n".join(lines)
