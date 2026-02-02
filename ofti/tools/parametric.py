from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core import postprocessing as postprocessing_core
from ofti.foamlib.parametric import build_parametric_cases
from ofti.foamlib.runner import run_cases
from ofti.tools.input_prompts import prompt_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _show_message
from ofti.ui_curses.viewer import Viewer


def foamlib_parametric_study_screen(  # noqa: C901
    stdscr: Any,
    case_path: Path,
) -> None:
    presets_path = case_path / "ofti.parametric"
    preset: postprocessing_core.ParametricPreset | None = None
    if presets_path.is_file():
        presets, errors = postprocessing_core.read_parametric_presets(presets_path)
        if errors:
            _show_message(stdscr, "Errors in ofti.parametric; falling back to manual input.")
        elif presets:
            labels = [preset_item.name for preset_item in presets]
            menu = build_menu(
                stdscr,
                "Parametric wizard",
                [*labels, "Manual entry", "Back"],
                menu_key="menu:parametric_wizard",
            )
            choice = menu.navigate()
            if choice == -1 or choice == len(labels) + 1:
                return
            if choice < len(labels):
                preset = presets[choice]

    dict_input = preset.dict_path if preset else "system/controlDict"
    entry = preset.entry if preset else ""
    values = preset.values if preset else []
    run_solver = False

    form = _parametric_form(stdscr, dict_input, entry, values, run_solver)
    if form is None:
        return
    dict_input, entry, values, run_solver = form

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
    value = prompt_line(stdscr, prompt)
    if value is None:
        return ""
    return value.strip()


def _parametric_form(
    stdscr: Any,
    dict_path: str,
    entry: str,
    values: list[str],
    run_solver: bool,
) -> tuple[str, str, list[str], bool] | None:
    while True:
        values_text = ", ".join(values) if values else "<none>"
        options = [
            f"Dictionary: {dict_path or 'system/controlDict'}",
            f"Entry: {entry or '<required>'}",
            f"Values: {values_text}",
            f"Run solver: {'yes' if run_solver else 'no'}",
            "Run",
            "Back",
        ]
        menu = build_menu(
            stdscr,
            "Parametric wizard",
            options,
            menu_key="menu:parametric_form",
            item_hint="Edit field or run.",
        )
        choice = menu.navigate()
        if choice in (-1, len(options) - 1):
            return None
        handlers = {
            0: _update_parametric_dict,
            1: _update_parametric_entry,
            2: _update_parametric_values,
            3: _toggle_parametric_run,
        }
        if choice in handlers:
            dict_path, entry, values, run_solver = handlers[choice](
                stdscr, dict_path, entry, values, run_solver,
            )
            continue
        if choice == 4:
            result = _finalize_parametric(
                stdscr, dict_path, entry, values, run_solver,
            )
            if result is not None:
                return result


def _update_parametric_dict(
    stdscr: Any,
    dict_path: str,
    entry: str,
    values: list[str],
    run_solver: bool,
) -> tuple[str, str, list[str], bool]:
    updated = _prompt_line(
        stdscr,
        "Dictionary path (default system/controlDict): ",
    )
    return updated or "system/controlDict", entry, values, run_solver


def _update_parametric_entry(
    stdscr: Any,
    dict_path: str,
    entry: str,
    values: list[str],
    run_solver: bool,
) -> tuple[str, str, list[str], bool]:
    updated = _prompt_line(stdscr, "Entry key (e.g. application): ")
    return dict_path, (updated or entry), values, run_solver


def _update_parametric_values(
    stdscr: Any,
    dict_path: str,
    entry: str,
    values: list[str],
    run_solver: bool,
) -> tuple[str, str, list[str], bool]:
    updated = _prompt_line(stdscr, "Values (comma-separated): ")
    if updated:
        values = [val.strip() for val in updated.split(",") if val.strip()]
    return dict_path, entry, values, run_solver


def _toggle_parametric_run(
    stdscr: Any,
    dict_path: str,
    entry: str,
    values: list[str],
    run_solver: bool,
) -> tuple[str, str, list[str], bool]:
    _ = stdscr
    return dict_path, entry, values, (not run_solver)


def _finalize_parametric(
    stdscr: Any,
    dict_path: str,
    entry: str,
    values: list[str],
    run_solver: bool,
) -> tuple[str, str, list[str], bool] | None:
    if not entry:
        _show_message(stdscr, "Entry key is required.")
        return None
    if not values:
        _show_message(stdscr, "Provide at least one value.")
        return None
    return dict_path or "system/controlDict", entry, values, run_solver
