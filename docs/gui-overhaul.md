# OFTI GUI Overhaul Notes

Source: user-provided redesign brief. This file preserves the important product/UX ideas without turning TODO.md into a design essay.

## Product direction

OFTI should feel like OpenFOAM mission control:

- setup like a CFD workbench;
- operate like K9s: continuously watched resources plus contextual commands;
- inspect like lazygit: complex operations discoverable without memorizing flags;
- edit like a cockpit-grade dictionary console;
- remain a cockpit over OpenFOAM, not a wrapper hiding OpenFOAM.

The current app has enough raw material: Vim-like navigation, command mode, shell escape, search, status-rich menus, live jobs, ETA, criteria, log metrics, boundary matrix, live tail, residual timeline, probes, yPlus, task monitor, shortcuts. The main weakness is information architecture: it is still a menu maze, not a control deck.

## Key redesign principle

Keep raw OpenFOAM visible and diffable at all times:

- Wizard view: semantic CFD intent, e.g. velocity inlet, speed, direction, turbulence model.
- Dictionary view: exact OpenFOAM paths/values, e.g. `0/U.boundaryField.inlet.type fixedValue`.
- Diff view: exact files and entries that will be written.

Never silently edit a running case. Queue runtime changes, show a diff, apply explicitly, then watch the log/filesystem for confirmation that the solver re-read the change.

## Target information architecture

Replace the current top-level menu with workflow tabs:

```text
[COCKPIT] [PREPARE] [MESH] [PHYSICS] [NUMERICS] [LAUNCH] [FLIGHT] [ANALYZE] [OPS]
```

Recommended tree:

```text
Cockpit
Prepare
  Case identity
  Solver selector
  OpenFOAM environment
  Template / clone / import
  Preflight
Mesh
  Mesh source
  blockMesh
  snappyHexMesh
  cfMesh
  checkMesh
  decompose / reconstruct
  mesh quality dashboard
Physics
  Regions
  Materials / thermo
  Turbulence
  Boundary conditions
  Initial conditions
  Source terms / fvOptions
Numerics
  fvSchemes
  fvSolution
  time controls
  relaxation
  residualControl
  function objects
  result controls
Launch
  Pipeline
  Serial run
  Parallel run
  HPC / Slurm run
  dry run
  launch checklist
Flight
  Live monitor
  Jobs
  Runtime control
  Logs
  Alerts
  Kill / pause / resume / safe stop
Analyze
  Residuals
  Forces / moments
  Probes
  Sampling
  Fields
  yPlus
  ParaView / Catalyst
Case Ops
  diff
  snapshots
  clean
  archive
  report
```

Important split: Physics is physical model/BC setup. Numerics is solver controls, schemes, relaxation, convergence criteria, runtime controls, and function/result controls.

## Minimum shiny v1 screen set

1. Cockpit default screen
2. Launch checklist
3. Boundary matrix v2
4. Numerics deck
5. Monitors/result-control editor
6. Flight runtime-control deck
7. Log + residual split view
8. Change queue / diff
9. Case snapshots
10. Command palette

Current screen remap:

```text
Old Overview        -> Cockpit summary panel
Old Mesh            -> Mesh deck
Old Physics & BC    -> Physics deck + Boundary matrix
Old Simulation      -> Launch + Flight
Old Post-Processing -> Analyze + monitor widgets
Old Config Manager  -> Prepare + Change queue + Dict inspector
Old Task monitor    -> Flight jobs panel
Old Command mode    -> Command palette
```

## Cockpit screen

Default screen should be persistent and alive, not a vertical menu. Suggested layout:

- top bar: solver, run state, latest time/iteration, deltaT, Co, ETA, mesh/env/log/pid;
- left: flight plan / workflow phase status;
- center: live telemetry, residual sparklines, forces/probes/yPlus summaries;
- right: alert/action cards;
- bottom: bounded live log tail and action bar.

The existing overview/status/log/criteria/ETA services already provide much of this data; the work is mostly layout and state composition.

## Flight runtime-control deck

Flight should be a live operating mode, not a flat Simulation submenu. It should group:

- jobs/processes;
- runtime control entries (`deltaT`, `endTime`, `writeInterval`, `purgeWrite`);
- stop criteria/residual targets;
- active monitors;
- safe actions: write now, edit deltaT/endTime, reload dicts, safe stop, terminate, pause, resume, adopt pid.

Runtime mutations must go through a change queue:

```text
Runtime change queue
  deltaT         0.001 -> 0.0005
  endTime        1.0   -> 2.0
  writeInterval  0.05  -> 0.01
  residualControl.U -> 1e-5
Mode: safe edit
Effect: write dictionaries, wait for solver reload, verify log acknowledgement
```

## Launch checklist

Replace blind `Run solver` with a go/no-go screen:

- case identity and solver;
- mesh/checkMesh status;
- physics and BC completeness;
- numerics validation;
- parallel/decompose readiness;
- monitors/result controls enabled;
- log rotation/snapshot strategy;
- explicit launch/dry-run/parallel wizard/edit failing item actions.

## Boundary matrix v2

Preserve and strengthen the current boundary matrix. Add semantic BC tooling:

- role wizard: inlet, outlet, wall, symmetry, empty, cyclic, wedge, interface;
- patch groups, e.g. inlets/walls/car_body;
- column paste/bulk apply per field;
- compatibility checks: patch type vs BC type, dimensions, turbulence wall functions, 2D empty consistency;
- selected-cell inspector with raw value and warnings;
- always support diff before write.

## Numerics deck

Make numerics first-class instead of hidden in config/simulation menus:

- fvSolution algorithm summary: SIMPLE/PIMPLE/PISO, correctors;
- relaxation factors;
- solver tolerances and relTol;
- fvSchemes summary;
- convergence contract sourced from residualControl / runtime criteria;
- transparent presets: conservative steady RANS, faster steady RANS, transient PIMPLE stable, high-speed compressible, custom;
- every preset shows dictionary diff before writing.

## Monitors/result-control editor

Move monitors before launch. Treat residuals, Courant, forces, probes, yPlus, sampling, and field calculations as mission-plan objects, not only post-processing screens.

Needed features:

- active monitor list;
- stop/alert rules;
- write functionObjects;
- diff before write;
- validate monitor prerequisites, patch names, fields, and probe points.

## Alert cards

Replace raw warning dumps in the cockpit with compact alert cards. Every alert should answer:

- what is wrong?
- why should I care?
- where did it come from?
- what can I do now?
- what file will be changed?

Example categories: mesh quality, missing BCs, stale log, divergent residuals, high Courant, missing monitor output, invalid runtime edit.

## Universal inspector

Use a tree + property/inspector pattern for setup screens:

- left: setup tree/entity list;
- right: selected entity details, OpenFOAM source path, status, actions;
- bottom: action hints and command palette.

This preserves familiar CFD-GUI structure without requiring a mouse.

## Command palette

Upgrade command mode from raw commands toward a fuzzy command palette with previews:

```text
: run parallel
: edit controlDict endTime
: monitor residuals
: add probe
: safe stop
: write now
: diff changes
: open latest log
: explain U boundary
```

Each command preview should show action, required state, files touched, diff option, and cancel path.

## Change queue and snapshots

Introduce a central change queue:

- staged dictionary/field changes grouped by file;
- apply all, view diff, snapshot+apply, discard;
- use snapshots before launch or destructive/high-risk writes;
- snapshot includes `system/`, `constant/`, `0/`, `Allrun`, and OFTI metadata.

## Visual style

Suckless spaceship:

- few colors, strong layout;
- green/OK, yellow/WARN, red/CRIT, cyan/ACTIVE, dim/stale;
- consistent glyphs: `*` or `●` running, `○` not configured, `✓` pass, `!` warning, `x` error, `>` selected;
- thin borders, dense telemetry, sparklines, one highlighted cursor, right-side inspector, bottom action bar;
- avoid decorative overload and giant banners except launch/failure screens.

## Architecture implications

Keep layering strict. Shared services first; UI screens are adapters.

Proposed service decomposition:

```text
OpenFOAM process supervisor
  starts/stops/adopts solver jobs
  knows pid, command, log, state

Telemetry collector
  tails logs
  parses residuals, Courant, execution time, forces, probes
  reads postProcessing time-value files

Case model
  parses system/, constant/, 0/
  exposes typed entries
  knows dirty/changed files

Monitor builder
  writes functionObjects
  validates probes/forces/yPlus/field calculations

Runtime controller
  writes safe controlDict/fvSolution changes
  confirms via log or filesystem update
  supports safe stop/write now/endTime/deltaT where solver allows

UI state
  selected panel
  selected entity
  alert stack
  command palette
  change queue
```

Textual could be evaluated later for pane layout, keybindings, reactive updates, and possible browser mirroring, but this should not block the curses implementation. First extract services and implement the cockpit model behind the current UI layer.
