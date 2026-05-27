from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.tool_screens.runner import _show_message, run_tool_command, run_tool_command_capture
from ofti.core.case import read_number_of_subdomains
from ofti.core.checkmesh import format_checkmesh_summary
from ofti.core.templates import write_example_template
from ofti.core.tool_output import format_log_blob
from ofti.foam.config import key_hint
from ofti.foamlib import runner as foamlib_runner
from ofti.foamlib.adapter import FoamlibUnavailableError
from ofti.ui_curses.viewer import Viewer


def run_checkmesh(stdscr: Any, case_path: Path) -> None:
    result = run_tool_command_capture(
        stdscr,
        case_path,
        "checkMesh",
        ["checkMesh"],
        status="Running checkMesh...",
    )
    if result is None:
        return
    _show_checkmesh_summary(stdscr, result.stdout, result.stderr)


def run_blockmesh(stdscr: Any, case_path: Path) -> None:
    ok, message = blockmesh_once(case_path)
    if ok:
        _show_message(stdscr, message)
        return
    if message == "foamlib unavailable":
        run_tool_command(
            stdscr,
            case_path,
            "blockMesh",
            ["blockMesh"],
            status="Running blockMesh...",
        )
        return
    _show_message(stdscr, message)


def blockmesh_once(case_path: Path) -> tuple[bool, str]:
    try:
        foamlib_runner.block_mesh_case(case_path, check=True, log="log.blockMesh")
    except FoamlibUnavailableError:
        return False, "foamlib unavailable"
    except Exception as exc:
        return False, f"blockMesh failed: {exc}"
    return True, "blockMesh completed."


def run_decomposepar(stdscr: Any, case_path: Path) -> None:
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        rel_path = Path("system") / "decomposeParDict"
        stdscr.clear()
        stdscr.addstr("Missing system/decomposeParDict.\n\n")
        stdscr.addstr("Press c to create from examples, or any other key to return.\n")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("c"), ord("C")):
            created = write_example_template(decompose_dict, rel_path)
            if created:
                _show_message(stdscr, "Created decomposeParDict from examples.")
            else:
                _show_message(stdscr, "No example template found for decomposeParDict.")
        return
    run_tool_command(
        stdscr,
        case_path,
        "decomposePar",
        ["decomposePar"],
        status="Running decomposePar...",
    )


def _show_checkmesh_summary(stdscr: Any, stdout: str, stderr: str) -> None:
    output = "\n".join([stdout or "", stderr or ""]).strip()
    summary = format_checkmesh_summary(output)
    stdscr.clear()
    stdscr.addstr(summary + "\n")
    back_hint = key_hint("back", "h")
    stdscr.addstr(f"Press r for raw output, {back_hint} to return.\n")
    stdscr.refresh()
    ch = stdscr.getch()
    if ch in (ord("r"), ord("R")):
        Viewer(
            stdscr,
            "\n".join(["checkMesh raw output", "", format_log_blob(stdout, stderr)]),
        ).display()


def _parallel_consistency_report(case_path: Path) -> tuple[str, list[str]]:
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        return ("missing", ["system/decomposeParDict not found."])

    expected = read_number_of_subdomains(decompose_dict)

    processors = _decomposed_processors(case_path)
    actual = len(processors)

    lines = []
    if expected is None:
        lines.append("numberOfSubdomains not set or invalid.")
    else:
        lines.append(f"numberOfSubdomains: {expected}")
    lines.append(f"processor* directories: {actual}")

    if expected is None:
        status = "warn"
    elif expected != actual:
        status = "mismatch"
    else:
        status = "ok"
    return (status, lines)


def parallel_consistency_screen(stdscr: Any, case_path: Path) -> None:
    status, lines = _parallel_consistency_report(case_path)
    header = "Parallel consistency check"
    if status == "missing":
        message = [header, "", *lines, "", "No decomposeParDict found."]
    elif status == "mismatch":
        message = [header, "", *lines, "", "Mismatch: re-run decomposePar or update dict."]
    elif status == "warn":
        message = [header, "", *lines, "", "Add numberOfSubdomains to decomposeParDict."]
    else:
        message = [header, "", *lines, "", "OK: counts match."]
    Viewer(stdscr, "\n".join(message)).display()


def _decomposed_processors(case_path: Path) -> list[Path]:
    return sorted(p for p in case_path.iterdir() if p.is_dir() and p.name.startswith("processor"))
