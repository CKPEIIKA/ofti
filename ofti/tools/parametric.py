from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core import postprocessing as postprocessing_core
from ofti.foamlib.parametric import (
    build_parametric_cases,
    build_parametric_cases_from_csv,
    build_parametric_cases_from_grid,
    preprocessing_available,
)
from ofti.foamlib.runner import run_cases
from ofti.tools.input_prompts import prompt_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _show_message
from ofti.ui_curses.viewer import Viewer


def foamlib_parametric_study_screen(
    stdscr: Any,
    case_path: Path,
) -> None:
    presets_path = case_path / "ofti.parametric"
    presets: list[postprocessing_core.ParametricPreset] = []
    if presets_path.is_file():
        presets, errors = postprocessing_core.read_parametric_presets(presets_path)
        if errors:
            _show_message(stdscr, "Errors in ofti.parametric; falling back to manual input.")
            presets = []

    selection = _select_parametric_mode(
        stdscr,
        presets,
        preprocessing_ready=preprocessing_available(),
    )
    if selection is None:
        return
    mode, preset = selection

    try:
        if mode == "single":
            flow = _run_single_parametric_flow(stdscr, case_path, preset)
        elif mode == "csv":
            flow = _run_csv_parametric_flow(stdscr, case_path)
        else:
            flow = _run_grid_parametric_flow(stdscr, case_path)
    except (OSError, RuntimeError, ValueError) as exc:
        _show_message(stdscr, f"Parametric setup failed: {exc}")
        return

    if flow is None:
        return
    created, run_solver = flow
    _show_parametric_results(stdscr, created, run_solver)


def _select_parametric_mode(
    stdscr: Any,
    presets: list[postprocessing_core.ParametricPreset],
    *,
    preprocessing_ready: bool,
) -> tuple[str, postprocessing_core.ParametricPreset | None] | None:
    if not presets and not preprocessing_ready:
        return "single", None

    labels: list[str] = []
    hints: list[str] = []
    actions: list[tuple[str, postprocessing_core.ParametricPreset | None]] = []
    disabled: set[int] = set()

    for preset in presets:
        labels.append(f"Preset: {preset.name}")
        hints.append("Load dictionary key and value list from ofti.parametric.")
        actions.append(("single", preset))

    labels.append("Single entry sweep")
    hints.append("One dictionary key, multiple values.")
    actions.append(("single", None))

    csv_idx = len(labels)
    labels.append("CSV study")
    hints.append("Build cases from CSV columns (foamlib preprocessing).")
    actions.append(("csv", None))

    grid_idx = len(labels)
    labels.append("Grid study")
    hints.append("Build combinations across multiple axes.")
    actions.append(("grid", None))

    if not preprocessing_ready:
        disabled.update({csv_idx, grid_idx})

    labels.append("Back")
    hints.append("Return without changes.")

    def hint_for(idx: int) -> str:
        if 0 <= idx < len(hints):
            return hints[idx]
        return ""

    status = None
    if not preprocessing_ready:
        status = "Install foamlib[preprocessing] to enable CSV and grid studies."

    menu = build_menu(
        stdscr,
        "Parametric wizard",
        labels,
        menu_key="menu:parametric_wizard",
        hint_provider=hint_for,
        disabled_indices=disabled,
        status_line=status,
        help_lines=_parametric_mode_help_lines(preprocessing_ready),
    )
    choice = menu.navigate()
    if choice in (-1, len(labels) - 1):
        return None
    return actions[choice]


def _run_single_parametric_flow(
    stdscr: Any,
    case_path: Path,
    preset: postprocessing_core.ParametricPreset | None,
) -> tuple[list[Path], bool] | None:
    dict_input = preset.dict_path if preset else "system/controlDict"
    entry = preset.entry if preset else ""
    values = list(preset.values) if preset else []
    run_solver = False
    form = _parametric_form(stdscr, dict_input, entry, values, run_solver)
    if form is None:
        return None
    dict_input, entry, values, run_solver = form
    created = build_parametric_cases(
        case_path,
        Path(dict_input),
        entry,
        values,
    )
    return created, run_solver


def _run_csv_parametric_flow(
    stdscr: Any,
    case_path: Path,
) -> tuple[list[Path], bool] | None:
    form = _parametric_csv_form(stdscr, "parametric.csv", False)
    if form is None:
        return None
    csv_path, run_solver = form
    created = build_parametric_cases_from_csv(case_path, Path(csv_path))
    return created, run_solver


def _run_grid_parametric_flow(
    stdscr: Any,
    case_path: Path,
) -> tuple[list[Path], bool] | None:
    form = _parametric_grid_form(stdscr, [], False)
    if form is None:
        return None
    axes, run_solver = form
    created = build_parametric_cases_from_grid(case_path, axes)
    return created, run_solver


def _show_parametric_results(stdscr: Any, created: list[Path], run_solver: bool) -> None:
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
            f"Dictionary file: {dict_path or 'system/controlDict'}",
            f"Entry key: {entry or '<required>'}",
            f"Sweep values: {values_text}",
            f"Run solver: {'yes' if run_solver else 'no'}",
            "Create cases",
            "Back",
        ]
        def hint_for(idx: int) -> str:
            hints = [
                "Path inside case, e.g. system/controlDict or constant/thermophysicalProperties",
                "Dictionary key (supports dotted keys), e.g. application or thermoType.transport",
                "Comma-separated values. Example: simpleFoam, pisoFoam",
                "Toggle whether to run solver in each created case",
                "Create variant case folders with selected values",
                "Return without changes",
            ]
            if 0 <= idx < len(hints):
                return hints[idx]
            return ""

        menu = build_menu(
            stdscr,
            "Parametric wizard",
            options,
            menu_key="menu:parametric_form",
            hint_provider=hint_for,
            status_line=(
                "Creates sibling case folders; existing destination folders cause an error"
            ),
            help_lines=_parametric_form_help_lines(),
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


def _parametric_csv_form(
    stdscr: Any,
    csv_path: str,
    run_solver: bool,
) -> tuple[str, bool] | None:
    while True:
        options = [
            f"CSV file: {csv_path}",
            f"Run solver: {'yes' if run_solver else 'no'}",
            "Create cases",
            "Back",
        ]

        def hint_for(idx: int) -> str:
            hints = [
                "CSV path relative to case root.",
                "Toggle whether to run solver in each created case.",
                "Create all case variants from the CSV table.",
                "Return without changes.",
            ]
            if 0 <= idx < len(hints):
                return hints[idx]
            return ""

        menu = build_menu(
            stdscr,
            "Parametric CSV study",
            options,
            menu_key="menu:parametric_csv_form",
            hint_provider=hint_for,
            help_lines=_parametric_csv_help_lines(),
        )
        choice = menu.navigate()
        if choice in (-1, len(options) - 1):
            return None
        if choice == 0:
            updated = _prompt_line(
                stdscr,
                "CSV path inside case (e.g. studies/parametric.csv): ",
            )
            if updated:
                csv_path = updated
            continue
        if choice == 1:
            run_solver = not run_solver
            continue
        if choice == 2:
            return csv_path, run_solver


def _parametric_grid_form(
    stdscr: Any,
    axes: list[dict[str, Any]],
    run_solver: bool,
) -> tuple[list[dict[str, Any]], bool] | None:
    while True:
        state = _grid_menu_state(axes, run_solver)

        menu = build_menu(
            stdscr,
            "Parametric grid study",
            state["options"],
            menu_key="menu:parametric_grid_form",
            hint_provider=lambda idx: _grid_hint_for(state, idx),
            disabled_indices={state["clear_idx"]} if not axes else set(),
            help_lines=_parametric_grid_help_lines(),
        )
        choice = menu.navigate()
        action = _apply_grid_choice(stdscr, axes, run_solver, choice, state)
        if action is None:
            return None
        if action["done"]:
            return action["result"]
        axes = action["axes"]
        run_solver = action["run_solver"]


def _grid_menu_state(axes: list[dict[str, Any]], run_solver: bool) -> dict[str, Any]:
    axis_labels = [_axis_label(idx, axis) for idx, axis in enumerate(axes)]
    add_idx = len(axis_labels)
    clear_idx = add_idx + 1
    run_idx = add_idx + 2
    create_idx = add_idx + 3
    back_idx = add_idx + 4
    options = [
        *axis_labels,
        "Add axis",
        "Clear axes",
        f"Run solver: {'yes' if run_solver else 'no'}",
        "Create cases",
        "Back",
    ]
    return {
        "axis_count": len(axis_labels),
        "add_idx": add_idx,
        "clear_idx": clear_idx,
        "run_idx": run_idx,
        "create_idx": create_idx,
        "back_idx": back_idx,
        "options": options,
    }


def _grid_hint_for(state: dict[str, Any], idx: int) -> str:
    axis_count = int(state["axis_count"])
    if idx < axis_count:
        return "Edit selected axis."
    hints = {
        int(state["add_idx"]): "Add a dictionary key axis with value list.",
        int(state["clear_idx"]): "Remove all currently configured axes.",
        int(state["run_idx"]): "Toggle whether to run solver in each created case.",
        int(state["create_idx"]): "Create all combinations from configured axes.",
        int(state["back_idx"]): "Return without changes.",
    }
    return hints.get(idx, "")


def _apply_grid_choice(
    stdscr: Any,
    axes: list[dict[str, Any]],
    run_solver: bool,
    choice: int,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    axis_count = int(state["axis_count"])
    add_idx = int(state["add_idx"])
    clear_idx = int(state["clear_idx"])
    run_idx = int(state["run_idx"])
    create_idx = int(state["create_idx"])
    back_idx = int(state["back_idx"])
    if choice in (-1, back_idx):
        return None
    result: dict[str, Any] = {
        "axes": axes,
        "run_solver": run_solver,
        "done": False,
        "result": None,
    }
    if choice < axis_count:
        updated = _edit_grid_axis(stdscr, axes[choice])
        if updated is not None:
            axes[choice] = updated
    elif choice == add_idx:
        new_axis = _edit_grid_axis(stdscr, None)
        if new_axis is not None:
            axes.append(new_axis)
    elif choice == clear_idx:
        result["axes"] = []
    elif choice == run_idx:
        result["run_solver"] = not run_solver
    elif choice == create_idx:
        if not axes:
            _show_message(stdscr, "Add at least one axis first.")
        else:
            result["done"] = True
            result["result"] = (axes, run_solver)
    return result


def _edit_grid_axis(stdscr: Any, axis: dict[str, Any] | None) -> dict[str, Any] | None:
    current = axis or {}
    dict_default = str(current.get("dict_path") or "system/controlDict")
    entry_default = str(current.get("entry") or "")
    values_default = ", ".join(current.get("values", []))

    dict_path = _prompt_line(
        stdscr,
        f"Dictionary path [{dict_default}]: ",
    )
    entry = _prompt_line(
        stdscr,
        f"Entry key [{entry_default or 'required'}]: ",
    )
    values_text = _prompt_line(
        stdscr,
        f"Values comma-separated [{values_default or 'required'}]: ",
    )

    dict_path = dict_path or dict_default
    entry = entry or entry_default
    values = _split_values(values_text or values_default)
    if not entry:
        _show_message(stdscr, "Entry key is required.")
        return None
    if not values:
        _show_message(stdscr, "Provide at least one value.")
        return None
    return {
        "dict_path": dict_path,
        "entry": entry,
        "values": values,
    }


def _axis_label(index: int, axis: dict[str, Any]) -> str:
    dict_path = str(axis.get("dict_path") or "system/controlDict")
    entry = str(axis.get("entry") or "<entry>")
    values = ",".join(str(item) for item in axis.get("values", [])) or "<values>"
    return f"Axis {index + 1}: {dict_path} | {entry} | {values}"


def _split_values(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _update_parametric_dict(
    stdscr: Any,
    dict_path: str,
    entry: str,
    values: list[str],
    run_solver: bool,
) -> tuple[str, str, list[str], bool]:
    updated = _prompt_line(
        stdscr,
        "Dictionary path inside case (default system/controlDict): ",
    )
    return updated or "system/controlDict", entry, values, run_solver


def _update_parametric_entry(
    stdscr: Any,
    dict_path: str,
    entry: str,
    values: list[str],
    run_solver: bool,
) -> tuple[str, str, list[str], bool]:
    updated = _prompt_line(
        stdscr,
        "Entry key (e.g. application or thermoType.transport): ",
    )
    return dict_path, (updated or entry), values, run_solver


def _update_parametric_values(
    stdscr: Any,
    dict_path: str,
    entry: str,
    values: list[str],
    run_solver: bool,
) -> tuple[str, str, list[str], bool]:
    updated = _prompt_line(
        stdscr,
        "Values (comma-separated, e.g. simpleFoam,pisoFoam): ",
    )
    if updated:
        values = _split_values(updated)
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
        _show_message(
            stdscr,
            "Entry key is required.\nExample: application or thermoType.transport",
        )
        return None
    if not values:
        _show_message(
            stdscr,
            "Provide at least one value.\nExample: simpleFoam, pisoFoam",
        )
        return None
    return dict_path or "system/controlDict", entry, values, run_solver


def _parametric_preset_help_lines() -> list[str]:
    return [
        "Parametric wizard creates one case folder per value.",
        "If ofti.parametric exists, choose a saved preset here.",
        "Use Manual entry when you want a one-off sweep.",
        "Destination folders are created next to the current case.",
    ]


def _parametric_form_help_lines() -> list[str]:
    return [
        "Dictionary file: path relative to case root.",
        "Entry key: supports dotted keys, e.g. thermoType.transport.",
        "Sweep values: comma-separated tokens.",
        "Output cases are named <case>_<entry>_<value>.",
        "Runtime artifacts are excluded from copies (processor*, logs, postProcessing).",
        "Use Run solver=yes only when the base case is already runnable.",
    ]


def _parametric_mode_help_lines(preprocessing_ready: bool) -> list[str]:
    lines = [
        "Single entry: one dictionary key with multiple values.",
        "Presets come from ofti.parametric when available.",
    ]
    if preprocessing_ready:
        lines += [
            "CSV study: generate cases from a CSV table.",
            "Grid study: generate Cartesian combinations from multiple axes.",
        ]
    else:
        lines.append("Install foamlib[preprocessing] for CSV/grid modes.")
    return lines


def _parametric_csv_help_lines() -> list[str]:
    return [
        "CSV must be inside the case folder.",
        "CSV parsing and case generation use foamlib preprocessing.",
        "Use Run solver=yes only when generated cases are runnable as-is.",
    ]


def _parametric_grid_help_lines() -> list[str]:
    return [
        "Each axis is dictionary path + entry key + comma-separated values.",
        "Grid study creates all value combinations across all axes.",
        "Axis keys support dotted notation (e.g. thermoType.transport).",
    ]
