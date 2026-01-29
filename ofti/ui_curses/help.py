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
        "High-speed helper computes U and p0 and writes internalField.",
        "Boundary matrix lets you edit BCs in a grid.",
    ]


def simulation_help() -> list[str]:
    return [
        "Run solvers and manage jobs.",
        "Run solver (live) shows progress + last log lines.",
        "Foamlib parametric study creates cases for multiple values.",
    ]


def postprocessing_help() -> list[str]:
    return [
        "Inspect logs and extract results.",
        "Residual timeline reads log history (foamlib).",
        "Probes viewer plots probe values as ASCII.",
    ]


def config_help() -> list[str]:
    return [
        "Browse and edit OpenFOAM dictionaries.",
        "Create missing config generates minimal stubs.",
        "Search uses fzf when available.",
    ]


def tools_help() -> list[str]:
    return [
        "Run OpenFOAM tools or presets.",
        "First item re-runs the last tool with the same args.",
        "Use :tool <name> to run any tool from command mode.",
    ]


def diagnostics_help() -> list[str]:
    return [
        "Environment and installation checks.",
        "Parallel consistency compares decomposeParDict with processor dirs.",
    ]


def clean_case_help() -> list[str]:
    return [
        "Housekeeping actions for logs and time directories.",
        "Use the pruner to keep every Nth time directory.",
    ]
