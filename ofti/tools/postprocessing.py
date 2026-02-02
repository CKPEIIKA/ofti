from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core import postprocessing as postprocessing_core
from ofti.foamlib.parametric import build_parametric_cases
from ofti.foamlib.runner import run_cases
from ofti.tools.input_prompts import prompt_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _show_message, run_tool_command
from ofti.ui_curses.viewer import Viewer


def postprocessing_browser_screen(stdscr: Any, case_path: Path) -> None:
    root = case_path / "postProcessing"
    if not root.is_dir():
        _show_message(stdscr, "postProcessing directory not found.")
        return
    files = postprocessing_core.collect_postprocessing_files(root)
    if not files:
        _show_message(stdscr, "No postProcessing files found.")
        return
    labels = ["Summary"] + [p.relative_to(case_path).as_posix() for p in files] + ["Back"]
    menu = build_menu(
        stdscr,
        "PostProcessing browser",
        labels,
        menu_key="menu:postprocessing_browser",
        item_hint="Open selected output.",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    if choice == 0:
        lines = postprocessing_core.postprocessing_summary(root)
        Viewer(stdscr, "\n".join(lines)).display()
        return
    path = files[choice - 1]
    try:
        text = path.read_text(errors="ignore")
    except OSError as exc:
        _show_message(stdscr, f"Failed to read {path.name}: {exc}")
        return
    Viewer(stdscr, text).display()


def sampling_sets_screen(stdscr: Any, case_path: Path) -> None:
    options = postprocessing_core.sampling_options(case_path)
    labels = [opt.label for opt in options] + ["Back"]
    disabled = {idx for idx, opt in enumerate(options) if not opt.enabled}
    menu = build_menu(
        stdscr,
        "Sampling & sets",
        labels,
        menu_key="menu:sampling_sets",
        item_hint="Run selected sampling tool.",
        disabled_indices=disabled,
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    opt = options[choice]
    if not opt.enabled:
        _show_message(stdscr, f"Missing {opt.required_path}.")
        return
    run_tool_command(
        stdscr,
        case_path,
        opt.label,
        opt.command,
        status=f"Running {opt.label}...",
    )


def parametric_presets_screen(stdscr: Any, case_path: Path) -> None:
    presets_path = case_path / "ofti.parametric"
    if not presets_path.is_file():
        _show_message(stdscr, "ofti.parametric not found in case directory.")
        return
    presets, errors = postprocessing_core.read_parametric_presets(presets_path)
    if errors:
        lines = ["PARAMETRIC PRESET ERRORS", "", *errors]
        Viewer(stdscr, "\n".join(lines)).display()
        return
    if not presets:
        _show_message(stdscr, "No presets found in ofti.parametric.")
        return
    labels = [preset.name for preset in presets] + ["Back"]
    menu = build_menu(
        stdscr,
        "Parametric presets",
        labels,
        menu_key="menu:parametric_presets",
        item_hint="Run selected preset.",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    preset = presets[choice]
    run_line = _prompt_line(stdscr, "Run solver for each case? [y/N]: ")
    run_solver = run_line.strip().lower().startswith("y")
    try:
        created = build_parametric_cases(
            case_path,
            Path(preset.dict_path),
            preset.entry,
            preset.values,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _show_message(stdscr, f"Parametric setup failed: {exc}")
        return

    failures: list[Path] = []
    if run_solver:
        failures = run_cases(created, check=False)

    lines = [
        f"Preset: {preset.name}",
        f"Created {len(created)} case(s):",
        *[f"- {path}" for path in created],
    ]
    if run_solver:
        if failures:
            lines += ["", "Failures:", *[f"- {path}" for path in failures]]
        else:
            lines += ["", "All cases completed."]
    Viewer(stdscr, "\n".join(lines)).display()


def _prompt_line(stdscr: Any, prompt: str) -> str:
    stdscr.clear()
    value = prompt_line(stdscr, prompt)
    if value is None:
        return ""
    return value
