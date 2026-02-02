from ofti.ui_curses.help import menu_hint


def test_menu_hints_cover_primary_menus() -> None:
    menus = {
        "menu:root": [
            "Mesh",
            "Physics & Boundary Conditions",
            "Simulation",
            "Post-Processing",
            "Clean case",
            "Config Manager",
            "Tools",
            "Quit",
        ],
        "menu:pre": [
            "Run blockMesh",
            "blockMesh helper",
            "Mesh quality",
            "snappyHexMesh staged",
            "Decompose",
            "Reconstruct manager",
            "renumberMesh",
            "transformPoints",
            "cfMesh",
            "Back",
        ],
        "menu:physics": [
            "Config Editor",
            "Boundary matrix",
            "Initial conditions",
            "Thermophysical wizard",
            "Check syntax",
            "Back",
        ],
        "menu:sim": [
            "Edit case pipeline",
            "Run case pipeline",
            "Run solver",
            "Run solver parallel",
            "Safe stop",
            "Resume solver",
            "Parametric wizard",
            "Back",
        ],
        "menu:post": [
            "Reconstruct manager",
            "View logs",
            "Open ParaView",
            "Residual timeline",
            "Log analysis summary",
            "PostProcessing browser",
            "Field summary",
            "Sampling & sets",
            "Probes viewer",
            "postProcess",
            "foamCalc",
            "Run shell script",
            "Back",
        ],
        "menu:clean": [
            "Clean all",
            "Remove all logs",
            "Clean time directories",
            "Clear parallel",
            "Time directory pruner",
            "Back",
        ],
        "menu:config": [
            "Config Editor",
            "Create missing config",
            "OpenFOAM environment",
            "Check syntax",
            "Search",
            "Back",
        ],
        "menu:tools": [
            "Re-run last tool",
            "Diagnostics",
            "Case doctor",
            "Run shell script",
            "Clone case",
            "Job status",
            "Stop job",
            "Physics helpers",
            "Back",
        ],
        "menu:tools_physics": [
            "High-speed helper",
            "yPlus estimator",
            "Back",
        ],
        "menu:create_case": [
            "Back",
        ],
        "menu:config_templates": [
            "Back",
        ],
        "menu:openfoam_env": [
            "Enter path manually",
            "Clear selection",
            "Back",
        ],
        "menu:logs_select": [
            "Back",
        ],
        "menu:logs_select_solver": [
            "Back",
        ],
        "menu:log_tail_select": [
            "Back",
        ],
        "menu:probes_select": [
            "Back",
        ],
        "menu:field_select": [
            "Back",
        ],
        "menu:script_select": [
            "Back",
        ],
        "menu:postprocessing_browser": [
            "Summary",
            "Back",
        ],
        "menu:sampling_sets": [
            "Back",
        ],
        "menu:parametric_presets": [
            "Back",
        ],
        "menu:pipeline_add": [
            "Back",
        ],
        "menu:postprocess_menu": [
            "Run with defaults (-latestTime)",
            "Select function from postProcessDict",
            "Enter args manually",
            "Back",
        ],
        "menu:postprocess_funcs": [
            "Back",
        ],
        "menu:foamcalc_menu": [
            "Run with foamCalcDict",
            "Common ops (mag/grad/div)",
            "Enter args manually",
            "Back",
        ],
        "menu:foamcalc_ops": [
            "Back",
        ],
        "menu:tool_dicts": [
            "Back",
        ],
        "menu:snappy_staged": [
            "Run snappyHexMesh",
            "Back",
        ],
    }
    for menu_key, labels in menus.items():
        for label in labels:
            assert menu_hint(menu_key, label), f"Missing hint for {menu_key}: {label}"
