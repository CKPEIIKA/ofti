from __future__ import annotations


def main_menu_help() -> list[str]:
    return [
        "Choose a top-level area (mesh, physics, run, post, config, tools).",
        "Use :tool <name> to run any tool without entering Tools.",
        "Clean case groups log/time cleanups in one place.",
    ]


def preprocessing_help() -> list[str]:
    return [
        "Mesh construction & quality tools.",
        "blockMesh helper previews vertices/blocks before running.",
        "snappy staged run toggles castellated/snap/layers in the dict.",
    ]


def physics_help() -> list[str]:
    return [
        "Edit case physics and boundary settings.",
        "Thermophysical wizard edits core thermo slots.",
        "Boundary matrix lets you edit BCs in a grid.",
    ]


def simulation_help() -> list[str]:
    return [
        "Run solvers and manage jobs.",
        "Pipeline uses Allrun with # OFTI-PIPELINE header.",
        "Edit pipeline lets you add/reorder steps from tools.",
        "Run current solver starts in background and logs to log.<solver>.",
        "Run solver (live) shows progress + last log lines.",
        "Parametric wizard creates cases for multiple values.",
    ]


def postprocessing_help() -> list[str]:
    return [
        "Inspect logs and extract results.",
        "Open ParaView creates a .foam file and launches paraview.",
        "Residual timeline reads log history (foamlib).",
        "Log analysis summarizes Courant/residuals/exec time.",
        "PostProcessing browser lists time/set outputs.",
        "Field summary shows internalField stats for latest time.",
        "Sampling & sets runs topoSet / sample / distribution if dicts exist.",
        "Probes viewer plots probe values as ASCII.",
    ]


def config_help() -> list[str]:
    return [
        "Browse and edit OpenFOAM dictionaries.",
        "Create missing config uses example templates when available.",
        "Search uses fzf when available.",
    ]


def tools_help() -> list[str]:
    return [
        "Run OpenFOAM tools or presets.",
        "High-speed helper computes U/p0 from Mach + T + gamma.",
        "yPlus estimator reports min/max/avg from yPlus output.",
        "First item re-runs the last tool with the same args.",
        "topoSet/setFields prompts run common setup utilities.",
        "Use :tool <name> to run any tool from command mode.",
    ]


def diagnostics_help() -> list[str]:
    return [
        "Environment and installation checks.",
        "Dictionary compare highlights missing top-level keys.",
        "Parallel consistency compares decomposeParDict with processor dirs.",
    ]


def clean_case_help() -> list[str]:
    return [
        "Housekeeping actions for logs and time directories.",
        "Use the pruner to keep every Nth time directory.",
    ]
