from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def collect_postprocessing_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def postprocessing_summary(root: Path) -> list[str]:
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


def read_parametric_presets(path: Path) -> tuple[list[ParametricPreset], list[str]]:
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


def sampling_options(case_path: Path) -> list[SamplingOption]:
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
