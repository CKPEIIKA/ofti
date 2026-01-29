from __future__ import annotations

import os
import shlex
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.times import latest_time
from ofti.core.tool_output import CommandResult, format_command_result, format_log_blob
from ofti.foam.config import get_config, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.subprocess_utils import run_trusted
from ofti.tools.helpers import resolve_openfoam_bashrc, with_bashrc
from ofti.ui_curses.layout import status_message
from ofti.ui_curses.viewer import Viewer


@dataclass
class LastToolRun:
    name: str
    kind: str
    command: list[str] | str


_LAST_TOOL_RUN: LastToolRun | None = None
_LAST_TOOL_STATUS: tuple[str, str, float] | None = None


def _no_foam_active() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("OFTI_NO_FOAM") == "1"


def _no_foam_hint() -> str:
    if _no_foam_active():
        return " (no-foam mode may prevent OpenFOAM tools from running)"
    return ""


def _with_no_foam_hint(message: str) -> str:
    hint = _no_foam_hint()
    return f"{message}{hint}" if hint else message


def _record_last_tool(name: str, kind: str, command: list[str] | str) -> None:
    global _LAST_TOOL_RUN  # noqa: PLW0603
    _LAST_TOOL_RUN = LastToolRun(name=name, kind=kind, command=command)


def get_last_tool_run() -> LastToolRun | None:
    return _LAST_TOOL_RUN


def _record_tool_status(name: str, status: str) -> None:
    global _LAST_TOOL_STATUS  # noqa: PLW0603
    _LAST_TOOL_STATUS = (name, status, time.time())


def last_tool_status_line() -> str | None:
    if _LAST_TOOL_STATUS is None:
        return None
    name, status, timestamp = _LAST_TOOL_STATUS
    if time.time() - timestamp > 8.0:
        return None
    return f"last tool: {name} {status}"


def tool_status_mode() -> str:
    mode = "no-foam" if os.environ.get("OFTI_NO_FOAM") == "1" else "foam"
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    suffix = f" ({wm_dir})" if wm_dir else ""
    return f"mode: {mode}{suffix}"


def _job_dir_hint() -> str | None:
    job_dir = os.environ.get("FOAM_JOB_DIR", "~/.OpenFOAM/jobControl")
    path = Path(job_dir).expanduser()
    if path.is_dir():
        return None
    return f"hint: FOAM_JOB_DIR missing at {path}. Create it with: mkdir -p {path}"


def _maybe_job_hint(name: str) -> str | None:
    if name in ("foamPrintJobs", "foamCheckJobs"):
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


def _tool_alias_keys(case_path: Path) -> list[str]:
    keys: list[str] = []

    base_tools = [
        ("blockMesh", ["blockMesh"]),
        ("setFields", ["setFields"]),
        ("snappyHexMesh", ["snappyHexMesh"]),
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

    keys += [
        _normalize_tool_name("checkmesh"),
        _normalize_tool_name("logs"),
        _normalize_tool_name("viewlogs"),
        _normalize_tool_name("residuals"),
        _normalize_tool_name("residual_timeline"),
        _normalize_tool_name("probes"),
        _normalize_tool_name("probesviewer"),
        _normalize_tool_name("highspeed"),
        _normalize_tool_name("high_speed"),
        _normalize_tool_name("highspeedhelper"),
    ]

    keys.extend(
        [
            _normalize_tool_name("rerun"),
            _normalize_tool_name("last"),
            _normalize_tool_name("runScript"),
            _normalize_tool_name("foamDictionary"),
            _normalize_tool_name("postProcess"),
            _normalize_tool_name("foamCalc"),
            _normalize_tool_name("topoSet"),
            _normalize_tool_name("setFields"),
            _normalize_tool_name("tool_dicts"),
            _normalize_tool_name("toolDicts"),
            _normalize_tool_name("runCurrentSolver"),
            _normalize_tool_name("runLive"),
            _normalize_tool_name("removeLogs"),
            _normalize_tool_name("cleanTimeDirs"),
            _normalize_tool_name("cleanCase"),
            _normalize_tool_name("reconstructManager"),
            _normalize_tool_name("timeDirPruner"),
            _normalize_tool_name("safeStop"),
            _normalize_tool_name("solveResume"),
            _normalize_tool_name("clone"),
            _normalize_tool_name("yPlus"),
        ],
    )

    return keys


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    stdscr.addstr("Press any key to continue.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()


def load_tool_presets(case_path: Path) -> list[tuple[str, list[str]]]:
    """
    Load extra tools from an optional per-case file `ofti.tools`.

    Format (one per line, lines starting with # are ignored):
      name: command with args
    Example:
      simpleFoam: simpleFoam -case .
    """
    cfg_path = case_path / "ofti.tools"
    return _load_presets_from_path(cfg_path)


def load_postprocessing_presets(case_path: Path) -> list[tuple[str, list[str]]]:
    """
    Load optional post-processing commands from `ofti.postprocessing`.
    Same format as `ofti.tools`.
    """
    cfg_path = case_path / "ofti.postprocessing"
    return _load_presets_from_path(cfg_path)


def _expand_command(cmd: list[str], case_path: Path) -> list[str]:
    latest = latest_time(case_path)
    return [part.replace("{{latestTime}}", latest) for part in cmd]


def _expand_shell_command(shell_cmd: str, case_path: Path) -> str:
    latest = latest_time(case_path)
    return shell_cmd.replace("{{latestTime}}", latest)


def _run_simple_tool(
    stdscr: Any,
    case_path: Path,
    name: str,
    cmd: list[str],
    *,
    allow_runfunctions: bool = True,
) -> None:
    status_message(stdscr, f"Running {name}...")
    expanded = _expand_command(cmd, case_path)
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if allow_runfunctions and wm_dir and get_config().use_runfunctions:
        cmd_str = " ".join(shlex.quote(part) for part in expanded)
        shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; runApplication {cmd_str}'
        _record_last_tool(name, "shell", shell_cmd)
        _run_shell_tool(stdscr, case_path, name, shell_cmd)
        return

    bashrc = resolve_openfoam_bashrc()
    if bashrc:
        cmd_str = " ".join(shlex.quote(part) for part in expanded)
        shell_cmd = f"{cmd_str}"
        _record_last_tool(name, "shell", shell_cmd)
        _run_shell_tool(stdscr, case_path, name, shell_cmd)
        return

    _record_last_tool(name, "simple", expanded)
    try:
        result = run_trusted(
            expanded,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return
    _record_tool_status(name, f"exit {result.returncode}")

    hint = _maybe_job_hint(name)
    summary = format_command_result(
        [f"$ cd {case_path}", f"$ {' '.join(cmd)}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
        hint=hint,
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


def _run_shell_tool(stdscr: Any, case_path: Path, name: str, shell_cmd: str) -> None:
    status_message(stdscr, f"Running {name}...")
    shell_cmd = with_bashrc(_expand_shell_command(shell_cmd, case_path))
    _record_last_tool(name, "shell", shell_cmd)
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    try:
        result = run_trusted(
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
    _record_tool_status(name, f"exit {result.returncode}")

    hint = _maybe_job_hint(name)
    summary = format_command_result(
        [f"$ cd {case_path}", f"$ bash --noprofile --norc -c {shell_cmd}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
        hint=hint,
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


def _write_tool_log(case_path: Path, name: str, stdout: str, stderr: str) -> None:
    if not stdout and not stderr:
        return
    log_path = case_path / f"log.{name}"
    content = "\n".join([f"tool: {name}", "", format_log_blob(stdout, stderr), ""])
    with suppress(OSError):
        log_path.write_text(content)
