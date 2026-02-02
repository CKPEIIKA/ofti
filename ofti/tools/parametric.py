from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.foamlib.parametric import build_parametric_cases
from ofti.foamlib.runner import run_cases
from ofti.tools import postprocessing as post_tools
from ofti.tools.runner import _show_message
from ofti.ui_curses.inputs import prompt_input
from ofti.ui_curses.menus import Menu
from ofti.ui_curses.viewer import Viewer


def foamlib_parametric_study_screen(  # noqa: C901, PLR0912
    stdscr: Any,
    case_path: Path,
) -> None:
    presets_path = case_path / "ofti.parametric"
    preset: post_tools.ParametricPreset | None = None
    if presets_path.is_file():
        presets, errors = post_tools._read_parametric_presets(presets_path)
        if errors:
            _show_message(stdscr, "Errors in ofti.parametric; falling back to manual input.")
        elif presets:
            labels = [preset_item.name for preset_item in presets]
            menu = Menu(stdscr, "Parametric wizard", [*labels, "Manual entry", "Back"])
            choice = menu.navigate()
            if choice == -1 or choice == len(labels) + 1:
                return
            if choice < len(labels):
                preset = presets[choice]

    if preset is not None:
        dict_input = preset.dict_path
        entry = preset.entry
        values = preset.values
    else:
        dict_input = _prompt_line(
            stdscr,
            "Dictionary path (default system/controlDict): ",
        )
        if not dict_input:
            dict_input = "system/controlDict"
        entry = _prompt_line(stdscr, "Entry key (e.g. application): ")
        if not entry:
            _show_message(stdscr, "Entry key is required.")
            return
        values_line = _prompt_line(stdscr, "Values (comma-separated): ")
        values = [val.strip() for val in values_line.split(",") if val.strip()]
        if not values:
            _show_message(stdscr, "No values provided.")
            return
    run_line = _prompt_line(stdscr, "Run solver for each case? [y/N]: ")
    run_solver = run_line.strip().lower().startswith("y")

    try:
        created = build_parametric_cases(
            case_path,
            Path(dict_input),
            entry,
            values,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _show_message(stdscr, f"Parametric setup failed: {exc}")
        return

    failures: list[Path] = []
    if run_solver:
        failures = run_cases(created, check=False)

    lines = [
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
    value = prompt_input(stdscr, prompt)
    if value is None:
        return ""
    return value.strip()
