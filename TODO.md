# TODO

Current actionable backlog, rebuilt from `docs/foamlib_survey.md`, `docs/foamlib_adoption.md`, `docs/layering.md`, and the GUI overhaul brief preserved in local ignored `gui-overhaul.md`.

## P0 - captains deck/control deck overhaul

- Expand Numerics deck beyond v0 read-only summaries into editable fvSchemes/fvSolution/relaxation presets with diff-before-write.
- Expand Launch checklist from go/no-go v1 into executable TUI actions: launch, dry-run, edit failing item, and parallel wizard.
- Expand Flight deck beyond v0 into live runtime mutation queue for safe stop, writeNow, deltaT/endTime, pause/resume, adopt, and log confirmation.
- Expand parallel resize/resume beyond CLI/TUI v0 with stronger live `writeNow` acknowledgement, full input snapshots, and rollback guidance.
- Expand Change Queue beyond v1 read-only VCS diff preview into snapshot+apply for case edits, presets, launch changes, and runtime mutations.
- Expand alert cards with alert-to-evidence navigation and command/action previews.
- Expand soundless alarm states into action confirmations; destructive actions must require a snapshot/diff path.
- Upgrade command mode toward a fuzzy command palette with previews for run/edit/monitor/safe-stop/diff/log actions.

## P1 - captains deck-grade CFD screens

- Add Braille mission scopes as OFTI's oscilloscope layer: residuals, Courant, forces, probes, mass imbalance, thermal fields, yPlus, performance, and sweep comparisons.
- Add a plot fallback stack: ASCII/block plots for dumb terminals, Unicode sparklines, Braille plots, optional Kitty/Sixel image previews, and external ParaView as the final fallback.
- Add full-screen scope controls: log scale, rolling window, cursor, zoom, target bands, and scope mode switching.
- Build Boundary Matrix v2 with patch roles, patch groups, column paste/bulk apply, selected-cell inspector, and compatibility checks.
- Add Patch Captains Deck details: role guess, patch area/normal, field BC status, live flux, reverse-flow detector, wall distance/yPlus summary, and bulk wall-function actions.
- Add a Numerics deck summarizing fvSolution/fvSchemes, relaxation, solver tolerances, convergence contract, and transparent presets with diffs.
- Add a Monitors / Result Control editor for residuals, Courant, forces, probes, yPlus, sampling, field calculations, and stop/alert rules.
- Expand Monitor Builder beyond v0 `system/controlDict.functions` writing into controlDict include wiring, test/validate flow, probes/forces/yPlus editors, and TUI integration.
- Add Autopilot / run-condition rules for stop/warn/writeNow/reduce-deltaT actions; show each rule as plain English and as the OpenFOAM dictionary snippet.
- Add a universal setup tree + right-side inspector pattern for Physics, Numerics, Monitors, and Case Ops screens.
- Expand the log + residual split view with alert-to-evidence links.
- Expand log folding beyond v0 signal folding into an interactive searchable folded/raw log view.
- Add anomaly cards for residual flatline, Co spikes, force plateau/stall, disk growth, stale logs, and suspicious runtime mutations.
- Keep wizard, dictionary, and diff views available for every write path; never hide raw OpenFOAM changes.

## P1 - run intelligence and reproducibility

- Expand the opt-in real OpenFOAM profile test suite beyond current canonical cases into stronger runtime dictionary reread evidence, cleanup verification, replay artifacts, and heavier compressible/HPC profiles.
- Add a Black Box recorder: interpreted timeline of launch, solver milestones, user edits, dictionary rereads, warnings, process events, and monitor milestones.
- Add Replay mode for finished runs with synchronized log cursor, residual/Co scopes, bookmarks, and exportable clips.
- Expand Case DNA beyond v0 identity/fingerprint into physics, turbulence, numerics, monitors, and parallel summaries.
- Add Dictionary Time Machine over snapshots: before launch, after user edits, after autopilot changes, final; include blame source for user/wizard/autopilot/template/external edits.
- Expand Case Doctor Pro / `ofti lint` beyond v0 missing dictionaries, pressure reference, decomposition sanity, and disk-risk settings into BC compatibility, dimensions, turbulence wall functions, and solver/physics mismatch.
- Add Explain Warning mode for alerts/lint findings with evidence, impact, suggested fix, affected file, diff, and ignore option.
- Expand Resource Watch beyond v1 free disk/time-dir/processor/log summary and write-setting risk into disk growth ETA and safe cleanup actions.
- Add one-key Markdown report generation with case summary, mesh quality, solver setup, BC table, residual/force/probe plots, warnings, dictionary diffs, and reproducibility fingerprint.

## P2 - multi-case and HPC control

- Expand Multi-case Flight Deck beyond v0 live grouped/sorted case grid into residuals, force metrics, alerts, kill/safe-stop/rerun, and Braille comparison plots.
- Expand Mesh Radar beyond v1 checkMesh metrics/warning bars/advice into hot patches, non-orthogonality/skewness distributions, and links to ParaView sets.
- Add mesh-quality heatmaps with block/Braille distributions for non-orthogonality, skewness, aspect ratio, and bad-cell counts.
- Add HPC / Slurm control panel with queue state, job id, case, nodes, runtime, logs, cancel/attach/submit actions, and reusable job templates.
- Add inline field previews with layered fallback: ASCII/block, Unicode sparklines, Braille, optional Kitty/Sixel raster previews, then external ParaView.

## P1 - foamlib integration cleanup

- Verify `foamlib` 1.5.7 round-trip behavior for nested dictionaries, field files, and OpenFOAM fork/version syntax.
- Extend field IO coverage for time directories: internal values, boundary values, and reconstructed-time cases.
- Use `foamlib` for read-only mesh/case metadata where practical, especially cells/faces/points without `checkMesh`.
- Replace custom boundary/dictionary parsing only where `foamlib` gives equivalent behavior with less code and stable formatting.
- Expose richer foamlib type metadata in entry preview/edit validation if available.

## P2 - layering and shared services

- Extract captains deck data into shared services: process supervisor, telemetry collector, case model, monitor builder, runtime controller, alert stack, and change queue.
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
- TUI Captains Deck exists and reuses read-only CLI services.
- TUI starts from a fast adaptive menu after case selection; Captains Deck opens on demand.
- Wide TUI menus show a cheap right-side inspector; small/SSH terminals keep a compact header and list-first layout.
- Captains Deck v0 panels are focusable and Enter opens selected panel details.
- Captains Deck v1 has manual refresh, cached periodic refresh while open, and a selected-panel compact layout for small/SSH terminals.
- Root menu inspector changes shape per workflow area with mode, focus, safety, and action hints.
- Top-level TUI navigation uses workflow tabs: Captains Deck, Prepare, Mesh, Physics, Numerics, Launch, Flight, Analyze, Case Ops.
- Physics/Numerics and Launch/Flight have separated workflow entry points while still reusing existing shared config/simulation services.
- Numerics deck v0 summarizes fvSchemes, fvSolution, and controlDict from a shared service.
- Launch checklist v0 exposes read-only go/no-go rows for case, solver, numerics, mesh, parallel, and monitors.
- Launch checklist v1 exposes explicit GO/NO-GO gate, log rotation strategy, safe action rows, and direct failing-item targets.
- Flight deck v0 exposes live status, jobs, criteria, ETA, and safe action hints from shared services.
- Parallel resize/resume v0 exists as `ofti run resize-parallel` and a TUI Flight action: snapshot, writeNow wait, reconstruct latest, clean processors, update subdomains, resume from latest, decompose latest, and restart.
- Captains Deck has alert cards v0, Case DNA v0 with setup fingerprint, mission scopes v0, Mesh Radar v0, Resource Watch v0, and folded log v0.
- Captains Deck alert cards v1 show alarm state plus impact, evidence, suggested action, affected files, and source command.
- Resource Watch v1 flags risky `writeInterval`/`purgeWrite` settings; Mesh Radar v1 adds more checkMesh metrics and read-only advice.
- Case Doctor Pro / `ofti knife lint` v0 exists with evidence/advice findings for doctor issues, pressure reference, decomposition sanity, and resource risks.
- TUI Captains Deck shows Case Lint findings explicitly alongside Case Doctor.
- Shared captains deck service and `ofti knife captains-deck` / `dna` / `scopes` / `mesh-radar` / `resource` expose the read-only captains deck data outside the TUI.
- Change Queue v1 is read-only and shared by the TUI Config menu and `ofti knife changes`, including a bounded VCS diff preview.
- Monitor Builder v0 plans/writes `system/controlDict.functions` for residual/Courant/yPlus monitors with diff preview via `ofti knife monitors`.
- `ofti watch cases` has grouped/sorted live case grid output for queue-style monitoring.
- Opt-in real OpenFOAM/PyFoam profile harness exists for critical run-control flows and is skipped by default.
- Opt-in real OpenFOAM/PyFoam profile tests cover `icoFoam-cavity`, `simpleFoam-pitzDaily`, and `interFoam-damBreak`, with `OFTI_REAL_CASES` selection.
- Opt-in real OpenFOAM/PyFoam tests exercise prelaunch decks, lint/resource/mesh services, monitor builder writes, report artifact generation, untracked solver adoption, tracked live solver discovery, runtime controlDict mutation, change queue diffing, pause/resume/stop, optional parallel restart, and latest-time reconstruction.
- CLI table rendering exists for status/current/criteria/ETA/report, plot metrics/residuals, watch jobs, campaign summaries, and run status.
- Quality gate is `ruff`, `ty`, and full `pytest` with coverage target >=85%.
- Architecture rules are documented in `docs/architecture.md` and covered by import/layering tests.
- `ofti/core/times.py` is filesystem-only; OpenFOAM-assisted latest-time lookup lives in `ofti/foam/times.py`.
- `ofti/core/tool_dicts_service.py` no longer imports subprocess helpers; UI/tool adapters inject the OpenFOAM runner.
- `ofti/core/pipeline.py` no longer imports subprocess helpers; tool services inject the command runner.
- Watch CLI parser/output handlers live in `ofti/app/cli_handlers/watch.py`; `cli_tools.py` is smaller and remains a compatibility dispatcher for old tests/imports.
- Watch attach/start/run/log handling now lives in `ofti/app/cli_handlers/watch.py`; `cli_tools.py` only keeps compatibility aliases for those watch entry points.
- Run CLI parser plus tool/matrix/parametric/queue/status/resize/solver handlers live in `ofti/app/cli_handlers/run.py`; watch wrappers call the shared run handler instead of duplicating solver launch logic.
- Run manifest / receipt CLI handlers live in `ofti/app/cli_handlers/manifest.py`; `cli_tools.py` only maps their existing public handler names.
- Basic knife handlers live in `ofti/app/cli_handlers/knife_basic.py`: doctor, lint, changes, preflight, compare, copy, and set.
- Captains Deck/read-only knife handlers live in `ofti/app/cli_handlers/knife_deck.py`: initials, Captains Deck, DNA, scopes, monitors, mesh radar, resource watch, and CPU-mode helpers.
- Live/control knife handlers live in `ofti/app/cli_handlers/knife_live.py`: status, current, adopt, and stop.
- Analysis/campaign knife handlers live in `ofti/app/cli_handlers/knife_analysis.py`: convergence, stability, criteria, ETA, report, and campaign operations.
- Internal run manifest code replaces the old run_receipt module: pure core logic lives in `ofti/core/run_manifest.py`, OpenFOAM/git/ldd provenance lives in `ofti/foam/run_provenance.py`, and CLI/service wiring lives in `ofti/tools/run_manifest_service.py`.
- Internal run manifest naming is cleaned up in new code; only legacy persisted schema/user-facing receipt labels remain for compatibility.
- Core import tests now cover every `ofti/core/*.py` file without a subprocess exception.
- `ofti/app/cli_tools.py` is now a small dispatcher below 300 lines; compatibility lookup is lazy and handler bodies live in focused CLI adapter modules.
- Captains Deck aggregation now lives in `ofti/tools/captains_deck_service.py`; `ofti/app/overview.py` is mostly TUI/text rendering glue.
- Watch and run CLI parser construction live in `ofti/app/cli_handlers/watch_parser.py` and `ofti/app/cli_handlers/run_parser.py`; handler modules now focus on command behavior.
- Weak compatibility/helper modules were removed again: `cli_tools.py` imports `knife_parser.py` directly, and easy-on-CPU helpers are local to the few adapters that need them.
- Watch case-grid behavior lives in `ofti/app/cli_handlers/watch_cases.py`; run case-set behavior lives in `ofti/app/cli_handlers/run_cases.py`.
- `ofti knife manifest` is the preferred run-manifest command; `ofti knife receipt` remains as a compatibility alias.
- `--write-manifest` / `--manifest-file` are preferred run-start flags; legacy receipt flag names still work.
- Legacy `cockpit_service.py` was folded into `captains_deck_service.py`; Captains Deck payloads and table rendering now use Captains Deck names.

## P0 - clear architecture / layering plan

Target structure:

- `ofti/foamlib/`: optional foamlib integration only; no UI, no CLI formatting.
- `ofti/foam/`: OpenFOAM process/env/subprocess boundary.
- `ofti/core/`: pure OpenFOAM case/domain logic; no subprocess, no UI, no argparse.
- `ofti/tools/` now, later possibly `ofti/services/`: shared application workflows used by both CLI and TUI.
- `ofti/app/cli_handlers/`: argparse adapters and CLI output formatting by command group.
- `ofti/app/menus/` and `ofti/app/screens/`: TUI flows and screen controllers.
- `ofti/ui/`: UI-independent view models/contracts.
- `ofti/ui_curses/`: concrete curses widgets/rendering.
- `tests/`: mirror layers with explicit layering tests.

Implementation plan:

1. Freeze layer rules in `docs/architecture.md` and enforce them with import tests.
2. Finish CLI split so `ofti/app/cli_tools.py` is a dispatcher only; move remaining handler bodies into `ofti/app/cli_handlers/{knife,run,watch,plot}.py` or focused handler modules.
3. Rename/clarify CLI/service packages: `ofti/app/cli_handlers/*` are adapters; `ofti/tools/*` are shared workflows; consider `ofti/services/*` after the split stabilizes.
4. Clean core purity: move subprocess/OpenFOAM command calls out of `ofti/core`, starting with `foamListTimes` in `core/times.py`.
5. Split Captains Deck data aggregation out of `ofti/app/overview.py` into a shared Captains Deck service; TUI should only request payloads, render, and handle keys.
6. Separate view models from rendering: services return structured data; CLI/TUI render with their adapters; avoid services returning screen text except renderer-specific helpers.
7. Clarify TUI package intent: flows/controllers in app layer, widgets/primitives in `ui_curses`, contracts in `ui`.
8. Inventory services by purpose: case, run, telemetry, edit/change; keep names explicit and avoid UI imports.
9. Mirror architecture in tests: services tested directly; CLI/TUI tests cover wiring and output only; real OpenFOAM tests should hit services first.
10. Remove compatibility shims after migration: update tests to import new modules directly; keep only the public CLI entrypoint stable.

Concrete next architecture tasks:

- Split remaining oversized CLI behavior modules (`watch.py` and `run.py`) only around cohesive modes such as solver launch, watcher launch/attach, or external watcher rendering.
- Continue moving Captains Deck line rendering toward explicit view-models so services return structured data and adapters render it.
