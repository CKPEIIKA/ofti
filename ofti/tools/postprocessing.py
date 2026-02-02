from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    files = _collect_postprocessing_files(root)
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
        lines = _postprocessing_summary(root)
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
    options = _sampling_options(case_path)
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
    presets, errors = _read_parametric_presets(presets_path)
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


def _collect_postprocessing_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _postprocessing_summary(root: Path) -> list[str]:
    lines = ["POSTPROCESSING SUMMARY", "", f"Root: {root}", ""]
    for subdir in sorted(p for p in root.iterdir() if p.is_dir()):
        time_dirs = [d for d in subdir.iterdir() if d.is_dir() and _looks_like_time(d.name)]
        files = [p for p in subdir.rglob("*") if p.is_file()]
        lines.append(f"{subdir.name}: times={len(time_dirs)} files={len(files)}")
    if len(lines) == 4:
        lines.append("(no postProcessing subdirectories)")
    return lines


def _looks_like_time(name: str) -> bool:
    try:
        float(name)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class ParametricPreset:
    name: str
    dict_path: str
    entry: str
    values: list[str]


def _read_parametric_presets(path: Path) -> tuple[list[ParametricPreset], list[str]]:
    presets: list[ParametricPreset] = []
    errors: list[str] = []
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError as exc:
        return [], [f"Failed to read {path.name}: {exc}"]
    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 4:
                errors.append(f"Line {line_no}: expected 4 fields separated by |")
                continue
            name, dict_path, entry, values_raw = parts
        elif ":" in line:
            name_part, rest = line.split(":", 1)
            tokens = rest.strip().split()
            if len(tokens) < 2:
                errors.append(f"Line {line_no}: expected '<dict> <entry> <values>'")
                continue
            name = name_part.strip()
            dict_path = tokens[0]
            entry = tokens[1]
            values_raw = " ".join(tokens[2:]) if len(tokens) > 2 else ""
        else:
            errors.append(f"Line {line_no}: expected 'name | dict | entry | values'")
            continue
        values = [val.strip() for val in values_raw.split(",") if val.strip()]
        if not (name and dict_path and entry and values):
            errors.append(f"Line {line_no}: missing name, dict, entry, or values")
            continue
        presets.append(ParametricPreset(name, dict_path, entry, values))
    return presets, errors


@dataclass(frozen=True)
class SamplingOption:
    label: str
    command: list[str]
    required_path: Path
    enabled: bool


def _sampling_options(case_path: Path) -> list[SamplingOption]:
    topo = case_path / "system" / "topoSetDict"
    sample = case_path / "system" / "sampleDict"
    dist = case_path / "system" / "distributionDict"
    return [
        SamplingOption("Run topoSet", ["topoSet"], topo, topo.is_file()),
        SamplingOption(
            "Run sample (postProcess -func sample)",
            ["postProcess", "-func", "sample"],
            sample,
            sample.is_file(),
        ),
        SamplingOption(
            "Run distribution (postProcess -func distribution)",
            ["postProcess", "-func", "distribution"],
            dist,
            dist.is_file(),
        ),
    ]


def _prompt_line(stdscr: Any, prompt: str) -> str:
    stdscr.clear()
    value = prompt_line(stdscr, prompt)
    if value is None:
        return ""
    return value
