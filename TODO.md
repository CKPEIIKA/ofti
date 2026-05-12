# TODO

Current actionable backlog, rebuilt from `docs/foamlib_survey.md`, `docs/foamlib_adoption.md`, `docs/layering.md`, and the GUI overhaul brief preserved in local ignored `gui-overhaul.md`.

## P0 - cockpit/control deck overhaul

- Replace the default vertical main menu with a persistent Cockpit screen: run state, mesh/env/log health, ETA, criteria, residual/log telemetry, alerts, and action hints.
- Re-map top-level TUI navigation into workflow tabs: Cockpit, Prepare, Mesh, Physics, Numerics, Launch, Flight, Analyze, Case Ops.
- Split Physics from Numerics: keep materials/thermo/BCs/initials under Physics; move fvSchemes, fvSolution, relaxation, residualControl, runtime controls, and function/result controls into Numerics.
- Turn Simulation into Launch + Flight: add a launch checklist before solver runs and a live runtime-control deck for jobs, criteria, logs, safe stop, pause/resume, and adopt.
- Add a central change queue with diff-before-write and snapshot+apply for case edits, presets, launch changes, and runtime mutations.
- Add compact alert cards that explain impact, evidence, suggested action, and affected files instead of dumping raw warnings.
- Upgrade command mode toward a fuzzy command palette with previews for run/edit/monitor/safe-stop/diff/log actions.

## P1 - cockpit-grade CFD screens

- Expand mission scopes beyond v0 residual/Courant/performance dashboard plots to forces, probes, mass imbalance, yPlus, and full-screen Braille scope views.
- Add a plot fallback stack: ASCII/block plots for dumb terminals, Unicode sparklines, Braille plots, optional Kitty/Sixel image previews, and external ParaView as the final fallback.
- Build Boundary Matrix v2 with patch roles, patch groups, column paste/bulk apply, selected-cell inspector, and compatibility checks.
- Add Patch Cockpit details: role guess, patch area/normal, field BC status, live flux, reverse-flow detector, wall distance/yPlus summary, and bulk wall-function actions.
- Add a Numerics deck summarizing fvSolution/fvSchemes, relaxation, solver tolerances, convergence contract, and transparent presets with diffs.
- Add a Monitors / Result Control editor for residuals, Courant, forces, probes, yPlus, sampling, field calculations, and stop/alert rules.
- Add a Monitor Builder that writes `system/controlDict.functions` with diff/test/validate flow instead of requiring manual functionObject edits.
- Add Autopilot / run-condition rules for stop/warn/writeNow/reduce-deltaT actions; show each rule as plain English and as the OpenFOAM dictionary snippet.
- Add a universal setup tree + right-side inspector pattern for Physics, Numerics, Monitors, and Case Ops screens.
- Expand the log + residual split view with alert-to-evidence links.
- Expand log folding beyond v0 signal folding into an interactive searchable folded/raw log view.
- Keep wizard, dictionary, and diff views available for every write path; never hide raw OpenFOAM changes.

## P1 - run intelligence and reproducibility

- Add a Black Box recorder: interpreted timeline of launch, solver milestones, user edits, dictionary rereads, warnings, process events, and monitor milestones.
- Add Replay mode for finished runs with synchronized log cursor, residual/Co scopes, bookmarks, and exportable clips.
- Expand Case DNA beyond v0 identity/fingerprint into physics, turbulence, numerics, monitors, and parallel summaries.
- Add Dictionary Time Machine over snapshots: before launch, after user edits, after autopilot changes, final; include blame source for user/wizard/autopilot/template/external edits.
- Add Case Doctor Pro / `ofti lint` for BC compatibility, missing dictionaries, dimensions, turbulence wall functions, pressure reference, decomposition sanity, disk-risk settings, and solver/physics mismatch.
- Add Explain Warning mode for alerts/lint findings with evidence, impact, suggested fix, affected file, diff, and ignore option.
- Expand Resource Watch beyond v0 free disk/time-dir/processor/log summary into disk growth ETA, writeInterval risk, and safe cleanup actions.
- Add one-key Markdown report generation with case summary, mesh quality, solver setup, BC table, residual/force/probe plots, warnings, dictionary diffs, and reproducibility fingerprint.

## P2 - multi-case and HPC control

- Expand Multi-case Flight Deck beyond v0 live grouped/sorted case grid into residuals, force metrics, alerts, kill/safe-stop/rerun, and Braille comparison plots.
- Expand Mesh Radar beyond v0 checkMesh metrics/warning bars into hot patches, non-orthogonality/skewness distributions, and links to numerics advice or ParaView sets.
- Add HPC / Slurm control panel with queue state, job id, case, nodes, runtime, logs, cancel/attach/submit actions, and reusable job templates.

## P1 - foamlib integration cleanup

- Verify `foamlib` 1.5.7 round-trip behavior for nested dictionaries, field files, and OpenFOAM fork/version syntax.
- Extend field IO coverage for time directories: internal values, boundary values, and reconstructed-time cases.
- Use `foamlib` for read-only mesh/case metadata where practical, especially cells/faces/points without `checkMesh`.
- Replace custom boundary/dictionary parsing only where `foamlib` gives equivalent behavior with less code and stable formatting.
- Expose richer foamlib type metadata in entry preview/edit validation if available.

## P2 - layering and shared services

- Extract cockpit data into shared services: process supervisor, telemetry collector, case model, monitor builder, runtime controller, alert stack, and change queue.
- Move any reused CLI/TUI formatting or diagnostics out of screen modules into shared service/core modules.
- Keep UI modules as adapters: prompt, dispatch, display, keybinding, and error presentation only.
- Keep shell/OpenFOAM subprocess calls outside `ofti/core`; route them through `ofti/foam` or tool services.
- Review remaining direct file parsing in curses screens and route it through `core/entry_io.py` or foamlib-backed services.
- Evaluate Textual only after services are separated; do not block current curses improvements on a UI toolkit migration.

## P3 - Unix CLI polish

- Continue adding `--json` for automation and `--table` for structured human diagnostics where commands return tabular data.
- Keep output modes mutually exclusive and preserve stable exit codes: 0 success, 1 operational/check failure, 2 usage/input failure.
- Improve `-h/--help` on commands that still have bare positional names without practical descriptions.

## Done / no longer TODO

- Project depends on `foamlib[preprocessing,postprocessing]` by default.
- TUI Overview exists and reuses read-only CLI services.
- Overview has alert cards v0, Case DNA v0 with setup fingerprint, mission scopes v0, Mesh Radar v0, Resource Watch v0, and folded log v0.
- Shared cockpit service and `ofti knife cockpit` / `dna` / `scopes` / `mesh-radar` / `resource` expose the read-only cockpit data outside the TUI.
- `ofti watch cases` has grouped/sorted live case grid output for queue-style monitoring.
- CLI table rendering exists for status/current/criteria/ETA/report, plot metrics/residuals, watch jobs, campaign summaries, and run status.
- Quality gate is `ruff`, `ty`, and full `pytest` with coverage target >=85%.
