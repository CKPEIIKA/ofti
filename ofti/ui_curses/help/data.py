from __future__ import annotations

CONTEXT_HELP: dict[str, list[str]] = {
    "main": [
        "Choose a top-level area (mesh, physics, simulation, post, clean, config).",
        "Use :tool <name> or :run for direct command-mode shortcuts.",
        "Clean case groups cleanup helpers in one place.",
    ],
    "preprocessing": [
        "Mesh construction & quality tools.",
        "blockMesh helper previews vertices/blocks before running.",
        "snappy staged run toggles castellated/snap/layers in the dict.",
    ],
    "physics": [
        "Edit case physics and boundary settings.",
        "Thermophysical wizard edits core thermo slots.",
        "Boundary matrix lets you edit BCs in a grid.",
        "High-speed helper computes U/p0 from Mach + T + gamma.",
        "Initial conditions edits internalField for 0/ files (warns on 0.orig).",
    ],
    "simulation": [
        "Run solvers and manage jobs.",
        "Pipeline uses Allrun with # OFTI-PIPELINE header.",
        "Edit pipeline lets you add/reorder steps from tools.",
        "Run solver (live) shows progress + last log lines.",
        "Run solver (custom log) lets you choose a log path inside the case.",
        "Run solver (parallel) uses mpirun with safe prep defaults.",
        "Safe prep includes sync-subdomains and decomposePar prelaunch.",
        "Case status/current jobs and runtime checks reuse knife shared services.",
        "Current jobs can scan repo root recursively for campaign-wide live status.",
        "Runtime criteria/ETA/report are read-only diagnostics from logs/control.",
        "Convergence/stability checks are log-driven smoke diagnostics.",
        "Adopt supports bulk mode from repo root for untracked detached runs.",
        "Stop/pause/resume tracked jobs are in this stage.",
        "Parametric wizard creates cases for multiple values.",
    ],
    "postprocessing": [
        "Inspect logs and extract results.",
        "Open ParaView creates a .foam file and launches paraview.",
        "Residual timeline reads log history (foamlib).",
        "Log analysis is available inside View logs.",
        "PostProcessing browser lists time/set outputs.",
        "PostProcessing tables loads sampled tables via foamlib postprocessing extras.",
        "Field summary shows internalField stats for latest time.",
        "Sampling & sets runs topoSet / sample / distribution if dicts exist.",
        "Probes viewer plots probe values as ASCII.",
        "yPlus estimator summarizes yPlus output values.",
    ],
    "config": [
        "Use Config Editor to browse and edit dictionaries.",
        "Preflight/doctor/status checks are available here for setup phase.",
        "Initial fields summary shows internalField and boundary patch values.",
        "Set dictionary entry writes one key path directly into a dictionary file.",
    ],
    "tools": [
        "Run OpenFOAM tools or presets.",
        "Physics helpers include high-speed setup and yPlus checks.",
        "First item re-runs the last tool with the same args.",
        "Run tool in background tracks jobs in OFTI.",
        "Stop job sends SIGTERM to tracked jobs.",
        "Use :tool <name> to run any tool from command mode.",
    ],
    "tools_physics": [
        "Helpers for quick physics setup and diagnostics.",
        "High-speed helper computes U/p0 from Mach + T + gamma.",
        "yPlus estimator reports min/max/avg from yPlus output.",
    ],
    "diagnostics": [
        "Environment and installation checks.",
        "Dictionary compare highlights missing top-level keys.",
        "Parallel consistency compares decomposeParDict with processor dirs.",
    ],
    "clean": [
        "Housekeeping actions for logs and time directories.",
        "Clear parallel removes processor dirs and reconstructs latest time.",
        "Use the pruner to keep every Nth time directory.",
    ],
}

MENU_HINTS: dict[str, dict[str, str]] = {
    "menu:root": {
        "Mesh": "Mesh generation and quality tools.",
        "Physics & Boundary Conditions": "BCs, initial conditions, thermophysical setup.",
        "Simulation": "Run solver, pipeline, safe stop/resume.",
        "Post-Processing": "Logs, residuals, probes, sampling.",
        "Clean case": "Remove logs/time dirs and cleanup.",
        "Config Manager": "Browse/edit dictionaries and templates.",
        "Quit": "Exit OFTI.",
    },
    "menu:pre": {
        "Run blockMesh": "Run blockMesh using system/blockMeshDict.",
        "blockMesh helper": "Preview vertices/blocks before running.",
        "Mesh quality": "Run checkMesh and summarize quality.",
        "snappyHexMesh staged": "Toggle castellated/snap/layers then run.",
        "Decompose": "Decompose for parallel runs.",
        "Reconstruct manager": "Reconstruct decomposed results.",
        "renumberMesh": "Improve mesh ordering.",
        "transformPoints": "Transform mesh points (translate/scale/rotate).",
        "cfMesh": "Run cfMesh and view log.",
        "Back": "Return to main menu.",
    },
    "menu:physics": {
        "Config Editor": "Browse/edit physics dictionaries.",
        "Boundary matrix": "Edit boundary conditions in a grid.",
        "Initial conditions": "Edit internalField values (0/ or 0.orig).",
        "Thermophysical wizard": "Guided thermo/transport edits.",
        "High-speed helper": "Compute U and p0 from Mach inputs.",
        "Check syntax": "Validate dictionaries (foamlib).",
        "Back": "Return to main menu.",
    },
    "menu:sim": {
        "Edit case pipeline": "Edit Allrun pipeline steps.",
        "Run case pipeline": "Execute pipeline steps in order.",
        "Run solver": "Run solver with live log tail.",
        "Run solver (custom log)": "Run solver live and write to a chosen log path.",
        "Run solver parallel": "mpirun with sync-subdomains + optional prelaunch decomposePar.",
        "Case status": "Show solver/time/control summary for this case.",
        "Current jobs (live)": (
            "Show tracked jobs plus live untracked processes "
            "(supports repo-root recursive scope)."
        ),
        "Runtime criteria": "List normalized runtime criteria rows and status.",
        "ETA forecast": "Estimate ETA from criteria/endTime trends.",
        "Runtime report": "Show a compact status+metrics+criteria report.",
        "Convergence check": "Run log-based convergence quality checks.",
        "Stability check": "Run windowed signal stability check on solver log.",
        "Adopt untracked processes": (
            "Register discovered solver processes in jobs.json "
            "(including bulk campaign adoption)."
        ),
        "Stop tracked job": "Stop one tracked running job.",
        "Pause tracked job": "Pause one tracked running job.",
        "Resume tracked job": "Resume one paused tracked job.",
        "Safe stop": "Request graceful solver stop.",
        "Resume solver": "Start from latest time directory.",
        "Parametric wizard": "Generate case variants.",
        "Back": "Return to main menu.",
    },
    "menu:post": {
        "Reconstruct manager": "Reconstruct decomposed results.",
        "View logs": "Open logs menu (view/tail/analysis).",
        "Open ParaView": "Create .foam and launch ParaView.",
        "Residual timeline": "Sparkline summary of residuals.",
        "PostProcessing browser": "Browse postProcessing outputs.",
        "PostProcessing tables": "Load table sources with foamlib postprocessing.",
        "Field summary": "Internal field summary.",
        "Sampling & sets": "Run topoSet/sample/distribution.",
        "Probes viewer": "Plot probe values.",
        "yPlus estimator": "Parse yPlus output and summarize min/max/avg.",
        "foamCalc": "Run foamCalc with dict.",
        "Run shell script": "Execute a shell script in case dir.",
        "Back": "Return to main menu.",
    },
    "menu:view_logs": {
        "View log file": "Open a selected log in the text viewer.",
        "Tail log (live)": "Live tail with Courant/FPE/NaN highlights.",
        "[a] Log analysis summary": "Courant/execution/residual overview.",
        "Back": "Return to Post-Processing.",
    },
    "menu:clean": {
        "Clean all": "Logs + time dirs + processor dirs.",
        "Remove all logs": "Delete log.* files.",
        "Clean time directories": "Remove numeric time dirs.",
        "Clear parallel": "Remove processor dirs and reconstruct latest time.",
        "Time directory pruner": "Keep every Nth time directory.",
        "Back": "Return to main menu.",
    },
    "menu:tools": {
        "Re-run last tool": "Run the last tool again with the same args.",
        "Diagnostics": "Environment + case checks.",
        "Case doctor": "Check required files, mesh, syntax.",
        "Case operations": "Preflight/status/compare actions in native TUI.",
        "Run shell script": "Execute a shell script from the case folder.",
        "Clone case": "Copy case and clean mesh/time/logs.",
        "Job status": "View tracked background jobs.",
        "Stop job": "Stop a tracked background job.",
        "Physics helpers": "High-speed helper and yPlus estimator.",
        "Back": "Return to main menu.",
    },
    "menu:tools_physics": {
        "High-speed helper": "Compute U/p0 from Mach, T, gamma.",
        "yPlus estimator": "Parse yPlus output and summarize.",
        "Back": "Return to Tools menu.",
    },
    "menu:diagnostics": {
        "Case report": "Summary of solver, mesh, times, logs, disk usage.",
        "Dictionary compare": "Compare top-level dict keys vs another case.",
        "foamSystemCheck": "Run foamSystemCheck for env sanity.",
        "foamInstallationTest": "Run foamInstallationTest for install checks.",
        "Parallel consistency check": "Compare decomposePar vs processor dirs.",
        "Back": "Return to Tools menu.",
    },
    "menu:create_case": {
        "Back": "Return to case selector.",
    },
    "menu:config_templates": {
        "Back": "Return to Config Manager.",
    },
    "menu:openfoam_env": {
        "Enter path manually": "Set a custom OpenFOAM bashrc for this session.",
        "Clear selection": "Unset OFTI_BASHRC for this session.",
        "Back": "Return to Config Manager.",
    },
    "menu:logs_select": {
        "Back": "Return to logs menu.",
    },
    "menu:logs_select_solver": {
        "Back": "Return to logs menu.",
    },
    "menu:log_tail_select": {
        "Back": "Return to logs menu.",
    },
    "menu:probes_select": {
        "Back": "Return to Probes viewer.",
    },
    "menu:field_select": {
        "Back": "Return to field summary.",
    },
    "menu:script_select": {
        "Back": "Return to Tools menu.",
    },
    "menu:postprocessing_browser": {
        "Summary": "Show summary of postProcessing outputs.",
        "Back": "Return to Post-Processing.",
    },
    "menu:sampling_sets": {
        "Back": "Return to Post-Processing.",
    },
    "menu:parametric_presets": {
        "Back": "Return to Post-Processing.",
    },
    "menu:pipeline_add": {
        "Back": "Return to pipeline editor.",
    },
    "menu:postprocess_menu": {
        "Run with defaults (-latestTime)": "Run postProcess using latestTime.",
        "Select function from postProcessDict": "Pick a function from the dict.",
        "Enter args manually": "Provide custom postProcess args.",
        "Back": "Return to Post-Processing.",
    },
    "menu:postprocess_funcs": {
        "Back": "Return to postProcess menu.",
    },
    "menu:foamcalc_menu": {
        "Run with foamCalcDict": "Run foamCalc using foamCalcDict.",
        "Common ops (mag/grad/div)": "Pick common operators.",
        "Enter args manually": "Provide custom foamCalc args.",
        "Back": "Return to Post-Processing.",
    },
    "menu:foamcalc_ops": {
        "Back": "Return to foamCalc menu.",
    },
    "menu:tool_dicts": {
        "Back": "Return to Tools menu.",
    },
    "menu:snappy_staged": {
        "Run snappyHexMesh": "Write toggles then run snappyHexMesh.",
        "Back": "Return to Mesh menu.",
    },
    "menu:config": {
        "Config Editor": "Browse/edit dictionaries.",
        "Create missing config": "Create templates for missing dicts.",
        "Preflight checks": "Quick required-file and solver sanity checks.",
        "Case doctor": "Readiness diagnostics for case files and mesh.",
        "Case status": "Structured status view from knife service.",
        "Initial fields summary": "Summarize internalField and per-patch values in 0/ files.",
        "Set dictionary entry": "Set one dictionary key path to a new value.",
        "Compare dictionaries": "Compare dictionaries against another case path.",
        "Clone case": "Copy case template to a new sibling folder.",
        "Search": "Search keys across dictionaries.",
        "OpenFOAM environment": "Configure OpenFOAM environment.",
        "Check syntax": "Validate dictionaries (foamlib).",
        "Back": "Return to main menu.",
    },
}

TOOL_HELP: dict[str, list[str]] = {
    "renumbermesh": [
        "Reorders mesh cells for better cache locality.",
        "Runs renumberMesh and shows a summary log view.",
    ],
    "transformpoints": [
        "Translate/rotate/scale the mesh via transformPoints.",
        "Prompt for vectors or custom CLI args.",
    ],
    "cfmesh": [
        "Helper for running cartesianMesh + viewing its log.",
        "Requires system/cfMeshDict",
    ],
    "caseDoctor": [
        "Case readiness check (missing dicts, clock, syntax).",
        "Wraps verify_case via foamlib.",
    ],
    "jobStatus": [
        "Show tracked background jobs instead of foamPrintJobs.",
        "Status auto-refreshes and highlights logs.",
    ],
    "jobStart": [
        "Launch a tool in the background, capture stdout/stderr.",
        "Records PID/log and shows the tracker.",
    ],
    "jobStop": [
        "Send SIGTERM to a tracked job.",
        "Marks the job finished when the process exits.",
    ],
    "boundaryMatrix": [
        "Spreadsheet-style boundary condition editor for 0/ files.",
        "Enter edits a cell, P pastes snippets, F toggles patch filters, ? shows help.",
    ],
    "initialConditions": [
        "Table view of internalField values for 0/ fields.",
        "Enter opens the field editor; press ? for shortcuts and status hints.",
    ],
    "thermoWizard": [
        "Guided thermoProperties + transport editing.",
        "Templates cover thermoType, mixture, transport, and equationOfState blocks.",
        "Manual edits recommend Config Manager when files are missing.",
    ],
}
