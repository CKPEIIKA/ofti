# OFTI(1)

```
  ____  ______ _______ _____
 / __ \ |  ___|__   __|_   _|
| |  | | |__     | |    | |
| |  | |  __|    | |    | |
| |__| | |       | |   _| |_
 \____/|_|      |_|  |_____|
```

> ⚠️ This is vibe-coded software. Expect rough edges.

## NAME

ofti — OpenFOAM Terminal Interface

## SYNOPSIS

```
ofti [CASE]
ofti knife <command> [CASE] [--json | --table]
ofti run   <command> [CASE] [options]
ofti watch <command> [CASE] [options]
ofti plot  <command> [CASE] [options]
ofti bundle CASE --output ARCHIVE
ofti unbundle ARCHIVE --to CASE
ofti -h | -V
```

## DESCRIPTION

`ofti` is a CLI-first OpenFOAM helper with a curses interface on top. The CLI
provides scriptable diagnostics, run management, queueing, manifests, physical
field checks, and case operations. The TUI reuses the same core services for
interactive dictionary browsing/editing, boundary and initial-condition views,
and common tools (mesh, run, post-process, diagnostics).

When invoked with a valid case path, `ofti` opens the TUI on that case. When the
path is not an OpenFOAM case, or no path is given, the TUI first shows a case
chooser listing currently visible running solver cases, the current case when
applicable, and a "Choose from a directory" entry that opens a folder picker.

The first main-menu entry is `Overview`, a read-only dashboard that consolidates
safe CLI diagnostics such as case status, live jobs/processes, runtime criteria,
ETA, log metrics, and residual summaries. It uses the same table rendering as the
CLI instead of raw key/value dumps.

## INSTALLATION

From the repository root:

```bash
# uv (recommended)
uv tool install .
# or a local project venv:
uv venv
uv pip install -e .

# pip
python -m pip install .
# or editable for development:
python -m pip install -e .

# pipx (isolated app install)
pipx install .
```

`ofti` depends on `foamlib[preprocessing,postprocessing]` by default. If your
environment is missing optional OpenFOAM commands, CLI checks report the missing
capability and the TUI disables related actions with hints.

### PLUGINS

Optional domain plugins add solver-family diagnostics without putting
case-specific assumptions into OFTI core. This repository includes an
`ofti-hy2foam` plugin under `plugins/ofti-hy2foam` with hy2Foam-oriented field
presets, physical checks, charge observability, preflight checks, and same-mesh
patch comparison helpers.

The separate `plugins/hy2foam-mod` package is for modified/NN fork features
only. It layers over `ofti-hy2foam` and keeps `NNcompiled` / model-order checks
out of stock hy2Foam support and out of OFTI core.

Plugin knife commands are declared as framework-neutral `CommandSpec` objects
(`ofti.core.command_spec`) — a command exposes a `command_spec()` method that
names its positional arguments, options, and handler, and the active CLI adapter
builds the parser from that spec. Plugins do not touch argparse directly, and
they emit machine output through the shared output contract
(`ofti.core.output_contract.stamp_payload`) so plugin `--json` carries the same
`schema_version`/`command` envelope as core commands.

## CLI CONTRACT

- `-h` / `--help` is available at each command level.
- `-V` / `--version`, `--version`, and `ofti version` print the package version.
- `--json` is optional machine output for automation. Every JSON object carries
  a `schema_version` (currently `1`) and the `command` that produced it, so
  scripts can pin to a stable shape. Persisted JSON files use `format` and
  `format_version`; see `docs/formats.md`.
- OFTI endorses a future CLI JSON schema v2 with a stable
  `{ok, warnings, errors, data}` envelope. Schema v1 remains the compatible
  default until an explicit breaking-output switch is introduced.
- `--table` is optional aligned human output for structured read-only commands.
- `--json` and `--table` are mutually exclusive.
- `--easy-on-cpu` bounds log reads and slows polling to keep watch/status
  commands lighter on busy systems (the hidden legacy alias `--lightweight`
  still works).
- For streaming tails (`watch log --follow`, `watch attach`), JSON is only
  available in non-follow mode.
- Command output goes to `stdout`; parse/usage errors go to `stderr`.

### EXIT STATUS

- `0` — success
- `1` — operational failure / check failed
- `2` — invalid input / usage validation failure

## COMMANDS

`ofti` exposes non-interactive command groups plus top-level bundle helpers.
Prefer built-in help for command-level details:

```bash
ofti -h
ofti knife -h
ofti run -h
ofti watch log -h
ofti bundle -h
ofti unbundle -h
```

- **`bundle` / `unbundle`** — portable case archives with an embedded manifest
  and hash verification for moving a minimal runnable case to another host.
- **`knife`** — case inspection, diagnostics, and quick edits (status,
  preflight, doctor, criteria, ETA, initials, physical/compare-fields, copy,
  current/adopt, manifests). See *KNIFE WORKFLOWS* and *RUN MANIFESTS*.
- **`run`** — launch solvers and tools, parallel runs, queues, and parametric
  studies. See *RUN QUEUES* and *PARAMETRIC STUDIES*.
- **`watch`** — live monitoring of jobs, processes, and logs.
- **`plot`** — metric and criteria plotting.

External watcher integration (for example `scripts/oftools/ofwatch`) is expected
to run through tool presets in `ofti.tools` and can be executed with
`ofti run tool <name> --case CASE`.

## EXAMPLES

Diagnostics (`knife`):

```bash
ofti knife preflight CASE --json
ofti knife status CASE --table
ofti knife initials CASE --json
ofti knife physical CASE --time latest --fields p,U,rho,T --json
ofti knife physical CASE --field rho:min=0 --field T:min=0 --out checks
ofti knife compare-fields --reference SERIAL_CASE --candidate PARALLEL_CASE --preset flow --out compare
ofti knife copy CASE_COPY --case CASE
ofti knife current --root REPO --recursive --live --table
ofti knife adopt --root REPO --all-untracked --json
```

Running and queueing (`run`):

```bash
ofti run tool --list --case CASE --json
ofti run solver CASE --dry-run --json
ofti run solver CASE --parallel 8 --clean-processors --json
ofti run solver CASE --parallel 8 --no-prepare-parallel --json
ofti run resize-parallel CASE --from 8 --to 16 --json
ofti run smoke CASE --iterations 20 --timeout 5m --out smoke --json
ofti run matrix CASE --param application=simpleFoam,pisoFoam --no-launch --json
ofti run parametric CASE --entry application --values simpleFoam,pisoFoam --json
ofti run parametric CASE --csv studies/parametric.csv --run-solver --max-parallel 4 --json
ofti run status --set CASE_SET --fast --easy-on-cpu --json
```

`run resize-parallel` is the safe resume path for changing MPI size. It can ask
a live solver for `writeNow`, waits for the solver to stop, snapshots
`system/`, `constant/`, and `0/`, checks that all `processor*` directories have a
complete common latest time, reconstructs only that complete time, discards later
partial processor writes by cleaning old `processor*`, updates
`numberOfSubdomains`, sets `startFrom latestTime`, redecomposes, and optionally
restarts.

Portable case bundles:

```bash
ofti bundle CASE --output case.ofti.tar.gz --mesh auto --time 0 --json
ofti bundle CASE --output case.ofti.tar.gz --mesh include-polyMesh --table
ofti bundle CASE --output case.ofti.tar.gz --smoke --smoke-timeout 60s --json
ofti unbundle case.ofti.tar.gz --to CASE_COPY --json
ofti unbundle case.ofti.tar.gz --to CASE_COPY --table
ofti unbundle case.ofti.tar.gz --to CASE_COPY --run --background --json
```

Bundles contain the minimal runnable case tree: `system/`, `constant/`, the
selected start-time directory, local `#include "..."` files, optional
`Allrun`/`Allclean`, `ofti.*` metadata, and `constant/polyMesh` when requested
or auto-detected. They exclude logs, `processor*`, `postProcessing`, and caches
by default. OFTI refuses incomplete cases, warns about missing includes or mesh
requirements, and runs a lightweight dictionary syntax lint before archiving.

The deterministic `.tar.gz` archive embeds `.ofti/bundle.json` with file hashes,
solver application, detected OpenFOAM header version, warnings, and plugin
target-host hints. `unbundle` rejects unsafe archive paths/links, refuses
non-empty destinations unless `--force`, and verifies hashes after extraction.
`.tar.zst` is supported when the optional Python `zstandard` backend is
installed.

Use `bundle --smoke` before copying to prove the archive can be extracted and
run through a bounded solver smoke test on the current host. `unbundle --run`
executes the restored case through the same solver service as `ofti run solver`;
add `--background` to register a watchable job and still write a run manifest.

The slow real-case suite includes bundle/unbundle coverage for a toy OpenFOAM
case: it verifies manifest hashes, preflight/status on the restored copy, and a
bounded solver smoke run from the unbundled case.

Monitoring (`watch`) and plotting (`plot`):

```bash
ofti watch jobs CASE --table
ofti watch pause CASE --all
ofti watch resume CASE --all
ofti watch stop CASE --signal TERM
ofti watch log CASE --lines 80 --json
ofti watch log CASE --follow --easy-on-cpu
ofti plot metrics CASE --table
```

## KNIFE WORKFLOWS

Campaign-wide live status from a repo root:

```bash
ofti knife current --root . --recursive --live --json
```

- `jobs_tracked_running`: tracked jobs from the OFTI registry only.
- `jobs_running`: tracked + live untracked solver processes.
- `jobs_total`: tracked jobs + currently discovered untracked running processes.
- `runs`: canonical run view that collapses a launcher/wrapper and solver ranks
  into one row where OFTI can identify the process group.

Bulk-adopt externally launched runs under a repo root (the two forms are
equivalent):

```bash
ofti knife adopt --root . --all-untracked --json
ofti knife adopt --root . --recursive --json
```

Adopted runs are normalized into the same run registry used by `watch jobs`,
`knife current`, and `knife status`. When procfs access is limited, OFTI reports
that live process discovery may be incomplete instead of silently treating the
registry as empty.

If `.ofti/jobs.json` is lost or quarantined, rebuild it from durable run
identity files:

```bash
ofti knife registry repair CASE --json
```

Safe parallel launcher defaults (can be disabled explicitly):

```bash
ofti knife run CASE --parallel 2 --sync-subdomains --prepare-parallel --json
```

- `--sync-subdomains` updates `system/decomposeParDict:numberOfSubdomains`.
- `--prepare-parallel` runs parallel prelaunch (`decomposePar -force`, optional cleanup).
- Opt-out flags: `--no-sync-subdomains`, `--no-prepare-parallel`.

Runtime criteria respect explicit `runTimeControl` gate messages in logs:

- `Conditions not met` prevents premature auto-pass from numeric-only checks.
- Criteria stay `unknown`/unmet until gate lines report conditions are met.
- Unknown criteria include a reason such as not enough samples, no matching log
  samples, startup window, or unavailable trend.

For very large logs, analysis/tail paths use bounded recent log windows to stay
responsive, and the TUI log viewer falls back to a bounded tail view.

## RUN QUEUES

`ofti run queue` is the CLI-first queue primitive. By default it runs cases
sequentially (`--max-parallel 1`), records each solver log, waits for a case to
finish or crash, classifies the outcome, and immediately advances to the next
case:

```bash
ofti run queue case_a case_b --json
ofti run queue --set CASE_SET --glob 'case_*' --max-parallel 1
```

Queue result rows include `returncode`, `state`, `outcome`, `stop_reason`,
`latest_time`, and `end_time`. Outcomes distinguish normal end-time completion,
criterion completion when detectable, crashes, and unknown stopped cases. Use
bounded parallel queueing only when the per-case final return code is less
important than throughput:

Generic queue tests cover portable end-time and crash outcomes. Stronger
criterion-specific outcomes need explicit `runTimeControl` evidence in the case
or an external real profile, because OpenFOAM solvers do not expose one uniform
"criterion stopped" signal.

```bash
ofti run queue --set CASE_SET --glob 'case_*' --max-parallel 6 --backend foamlib-async
```

## PARAMETRIC STUDIES

CLI and TUI share the same foamlib-backed generation paths:

```bash
# single-entry sweep
ofti run parametric CASE --dict system/controlDict --entry application --values simpleFoam,pisoFoam

# CSV study
ofti run parametric CASE --csv studies/parametric.csv

# grid study
ofti run parametric CASE \
  --grid-axis application=simpleFoam,pisoFoam \
  --grid-axis constant/transportProperties:nu=1e-5,2e-5
```

Minimal CSV schema example (`studies/parametric.csv`):

```csv
application,transportModel,nu
simpleFoam,Newtonian,1e-05
pisoFoam,Newtonian,2e-05
```

Use `--run-solver` with `--max-parallel` to immediately queue generated cases.

## RUN MANIFESTS

Manifests capture reproducible-run provenance:

```bash
ofti run solver CASE --write-manifest --json
ofti run solver CASE --write-manifest --record-inputs-copy --json
ofti knife manifest write CASE --record-inputs-copy --json
ofti knife manifest verify runs/.../manifest.json --json
ofti knife manifest restore runs/.../manifest.json --to RESTORED_CASE --json
ofti knife manifest restore runs/.../manifest.json --to CASE_COPY --only system,constant --json
```

- `--write-manifest` writes an immutable manifest JSON under `./runs/` in the
  directory where you launch the command.
- Hash-only manifests are verification-grade: they let you detect drift.
- `--record-inputs-copy` upgrades the manifest to restore-grade by copying
  `system/`, `constant/`, and `0/` next to the manifest.
- Manifests also record build/runtime provenance: solver binary hash,
  linked-library hash set, compiler flags, and selected OpenFOAM environment
  variables.
- `--manifest-file` overrides the destination explicitly; relative paths resolve
  from the current working directory.
- `knife manifest verify` checks the current case against recorded hashes,
  including solver binary and linked-library drift.
- `knife manifest restore` recreates inputs only when the manifest includes the
  recorded input copy; `--only`/`--skip` restore selected roots from `system`,
  `constant`, and `0`.

## INTERACTIVE TUI

Main menu / interface sketch (example):

```text
*------------------------------*- ofti -*-------------------------------*
| Case: motorBike                     | Solver: simpleFoam              |
| Status: ran                         | Latest time: 0.0002             |
| Mesh: 7200 cells, faces=30006, ...  | Parallel: 10; (scotch;)         |
| Faces: 30006 Points: 16814          | Disk: 34.0MB                    |
| Env: v1706                          | Keys: ? help / search : cmd     |
| Path: /path/to/openfoam/case        | Log: log.simpleFoam             |
*------------------------------------------------------------------------*

Main menu

>> Overview
   Mesh
   Physics & Boundary Conditions
   Simulation
   Post-Processing
   Clean case
   Config Manager
   Quit

[normal mode: OpenFOAM env loaded | j/k move | Enter open | q quit]
```

### MODES

- **Normal**: OpenFOAM environment detected; tools available.
- **Limited**: OpenFOAM env not detected; tools are disabled, editor remains usable.

### EDITOR

- Browse `system/`, `constant/`, and `0*` files.
- Entry preview shows type, value, comments, and boundary info.
- Values are validated (dimensions, fields, vectors, etc.).
- `e`/`Enter` to edit; `v` to view file; `o` to open `$EDITOR`.

### STAGES AND COMMAND MODE

Common actions are grouped under Mesh, Physics, Simulation, Post‑Processing,
Clean case, and Config Manager. Actions are disabled with a clear reason when
required files/environment are missing.

Command-mode shortcuts:

- `:tool <name>` or `:<name>` runs tool aliases/presets.
- `:run ...`, `:knife ...`, `:watch ...`, `:plot ...` call the non-interactive CLI.

Post‑Processing notes:

- `View logs` contains file view, live tail, and log analysis summary.
- `PostProcessing tables` loads table-like outputs using foamlib postprocessing extras.
- `Sampling & sets` includes `postProcess`-driven sampling actions.
- `Parametric wizard` supports single-entry, CSV, and grid studies (when preprocessing extras are installed).

## ENVIRONMENT

- `OFTI_CONFIG` — path to the user config TOML (default
  `~/.config/ofti/config.toml`).
- `WM_PROJECT_DIR` and the standard OpenFOAM variables — used to detect the
  active environment and locate tools.

User config TOML, case-local preset files, runtime JSON records, and bundle
format rules are described in `docs/runtime-files.md` and `docs/formats.md`.
The global TOML config is for portable defaults only: working roots, queue and
bundle output roots, polling/tail limits, OpenFOAM bashrc, keybindings, and
display preferences. Case-specific solver/physics remain in native OpenFOAM
case files.

## FILES

- Case root with `system/controlDict`
- Optional presets: `ofti.tools`, `ofti.postprocessing`, `ofti.parametric`
- Logs: `log.*`
- Config: `~/.config/ofti/config.toml` (or `$OFTI_CONFIG`)

## REQUIREMENTS

- Python 3.11+
- `foamlib[preprocessing,postprocessing]` (dictionary IO, parametric generation, table loading)
- OpenFOAM environment on `PATH` for running tools (optional for read-only use)

## DEVELOPMENT

Quality gates:

- `ruff check`
- `ty check`
- `pytest` with coverage gate `--cov-fail-under=85`

Testing policy is in `docs/testing.md`: new tests should assert behavior, not
only raise coverage, and slow OpenFOAM tests stay opt-in.

Adapter layout:

- `ofti/app/cli.py`: top-level `ofti` entrypoint; delegates non-interactive
  groups to the CLI tools dispatcher and opens the TUI otherwise.
- `ofti/app/cli_tools.py`: compatibility dispatcher for legacy imports.
- `ofti/app/cli_adapters/`: argparse, output formatting, and exit-code mapping
  by command group (`knife`, `plot`, `watch`, `run`).
- `ofti/tools/` and `ofti/core/`: shared services and domain logic used by both
  CLI and TUI.
- `ofti/foamlib/`: the only direct upstream `foamlib` integration layer.

### REAL-CASE TESTS

Slow real-case tests are opt-in and exercise services against copied OpenFOAM
cases instead of fixtures:

```bash
OFTI_REAL_PROFILES='cavity=/path/to/case;solver=simpleFoam;tags=serial' \
  uv run pytest --runslow -m real_openfoam tests/test_real_openfoam_profiles.py
OFTI_REAL_SCENARIOS='smoke,queue,diagnostics' \
  OFTI_REAL_PROFILES='case=/path/to/case' \
  uv run pytest --runslow -m real_openfoam tests/test_real_openfoam_profiles.py
```

`OFTI_REAL_SCENARIOS` limits expensive checks by name. Current scenario names
include `runtime`, `smoke`, `diagnostics`, `start-stop`, `parallel-stop`,
`queue`, `queue-failure`, `foamlib-ops`, `core-services`, `parallel-resize`,
`parallel-resize-exec`, and `hpc`.

Canonical tutorial smoke coverage is also opt-in. It clones an OpenFOAM tutorial
case, runs `blockMesh`/`checkMesh`, then exercises OFTI services against the real
case copy:

```bash
OFTI_ENABLE_REAL_CASE_TESTS=1 OFTI_REAL_CASES=icoFoam-cavity \
  uv run pytest --runslow -m real_openfoam tests/test_real_openfoam_toy_case.py
```

Set `OFTI_REAL_CASE_ROOT`, `FOAM_TUTORIALS`, or `OFTI_TOY_CASE_TEMPLATE` when the
OpenFOAM tutorial tree is not discoverable from `WM_PROJECT_DIR`.

## LICENSE

GPL-3.0-or-later.
