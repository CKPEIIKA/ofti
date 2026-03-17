# DISCLAIMER

THIS IS VIBE-CODED SOFTWARE. EXPECT ROUGH EDGES.

# OFTI(1)

```
  ____  ______ _______ _____
 / __ \\ |  ___|__   __|_   _|
| |  | | |__     | |    | |
| |  | |  __|    | |    | |
| |__| | |       | |   _| |_
 \\____/|_|      |_|  |_____|
```

## NAME

ofti – OpenFOAM Terminal Interface (TUI)

## SYNOPSIS

```
python -m ofti.app.cli /path/to/case
ofti /path/to/case
```

Install from the repo root:

```bash
# uv (recommended)
uv tool install .
# or for local project venv:
uv venv
uv pip install -e .

# pip
python -m pip install .
# or editable for development:
python -m pip install -e .

# pipx (isolated app install)
pipx install .
```

`ofti` now depends on `foamlib[preprocessing,postprocessing]` by default.
If your environment is missing these extras, related features stay disabled in TUI with hints.

## DESCRIPTION

`ofti` is a small curses-based interface for OpenFOAM cases. It focuses on
fast browsing/editing of dictionaries, a boundary/initial-conditions view,
and common tools (mesh, run, post-process, diagnostics).

If the provided path is not an OpenFOAM case, `ofti` opens a folder picker
to select a valid case directory.

Main menu/interface sketch (example):

```text
*------------------------------*- ofti -*-------------------------------*
| Case: reactiveShockTube             | Solver: hy2Foam                 |
| Status: ran                         | Latest time: 0.0002             |
| Mesh: 7200 cells, faces=30006, ...  | Parallel: 10; (scotch;)         |
| Faces: 30006 Points: 16814          | Disk: 34.0MB                    |
| Env: v1706                          | Keys: ? help / search : cmd     |
| Path: /path/to/openfoam/case        | Log: log.hy2Foam                |
*------------------------------------------------------------------------*

Main menu

>> Mesh
   Physics & Boundary Conditions
   Simulation
   Post-Processing
   Clean case
   Config Manager
   Quit

[normal mode: OpenFOAM env loaded | j/k move | Enter open | q quit]
```

## NON-INTERACTIVE CLI

`ofti` also provides non-TUI commands:

```bash
ofti knife ...
ofti plot ...
ofti watch ...
ofti run ...
```

Use built-in help at each level:

```bash
ofti -h
ofti -V
ofti knife -h
ofti watch log -h
ofti run tool -h
```

Most commands support `--json` for machine-readable output.
For streaming tails (`watch log --follow` / `watch attach`), JSON is only for
non-follow mode.

Examples:

```bash
ofti knife preflight CASE --json
ofti knife initials CASE --json
ofti knife copy CASE_COPY --case CASE
ofti knife current --root REPO --recursive --live --json
ofti knife adopt --root REPO --all-untracked --json
ofti watch jobs CASE --json
ofti watch pause CASE --all
ofti watch resume CASE --all
ofti watch stop CASE --signal TERM
ofti watch log CASE --lines 80 --json
ofti run tool --list --case CASE --json
ofti run solver CASE --dry-run --json
ofti run solver CASE --parallel 8 --clean-processors --json
ofti run solver CASE --parallel 8 --no-prepare-parallel --json
ofti run matrix CASE --param application=simpleFoam,pisoFoam --no-launch --json
ofti run parametric CASE --entry application --values simpleFoam,pisoFoam --json
ofti run parametric CASE --csv studies/parametric.csv --run-solver --max-parallel 4 --json
ofti run parametric CASE --grid-axis application=simpleFoam,pisoFoam --grid-axis transport:nu=1e-5,2e-5 --json
ofti run queue --set CASE_SET --glob 'case_*' --max-parallel 6 --backend foamlib-async --json
ofti run status --set CASE_SET --fast --json
```

### Knife Workflows (New)

Campaign-wide live status from repo root:

```bash
ofti knife current --root . --recursive --live --json
```

- `jobs_tracked_running`: tracked jobs from OFTI registry only.
- `jobs_running`: tracked + live untracked solver processes.
- `jobs_total`: tracked jobs + currently discovered untracked running processes.

Bulk-adopt externally launched runs under repo root:

```bash
ofti knife adopt --root . --all-untracked --json
```

Equivalent explicit form:

```bash
ofti knife adopt --root . --recursive --json
```

Safe parallel launcher defaults (can be disabled explicitly):

```bash
ofti knife run CASE --parallel 2 --sync-subdomains --prepare-parallel --json
```

- `--sync-subdomains` updates `system/decomposeParDict:numberOfSubdomains`.
- `--prepare-parallel` runs parallel prelaunch (`decomposePar -force`, optional cleanup).
- Optional opt-out flags: `--no-sync-subdomains`, `--no-prepare-parallel`.

Runtime criteria now respect explicit runTimeControl gate messages in logs:

- `Conditions not met` prevents premature auto-pass from numeric-only checks.
- Criteria stay `unknown`/unmet until gate lines report conditions are met.

For very large logs, analysis/tail commands read recent log windows to stay
responsive.

External watcher integration (for example `scripts/oftools/ofwatch`) is
expected to run through tool presets in `ofti.tools` and can be executed with
`ofti run tool <name> --case CASE`.

More command-level examples: `docs/knife_tools.md`

## UNIX CLI CONTRACT

- `-h/--help` is available at each command level.
- `-V/--version`, `--version`, and `ofti version` print the package version.
- `--json` is optional machine output for automation.
- Command output goes to `stdout`; parse/usage errors go to `stderr`.
- Exit codes:
  - `0` success
  - `1` operational failure/check failed
  - `2` invalid input/usage validation failure

## REQUIREMENTS

- Python 3.10+
- `foamlib[preprocessing,postprocessing]` (dictionary IO, parametric generation, table loading)
- OpenFOAM environment on `PATH` for running tools (optional for read-only)

## DEVELOPMENT QUALITY

Current repo checks:

- `ruff check`
- `ty check`
- `pytest` with coverage gate `--cov-fail-under=80`

## MODES

- **Normal**: OpenFOAM environment detected; tools available.
- **Limited**: OpenFOAM env not detected; tools are disabled, editor remains usable.

## KEYS (GLOBAL)

- `j/k` or arrows: move
- `Enter`: select
- `h` or `Esc`: back
- `q`: quit (root menu only)
- `/`: menu search with `fzf` (if installed)
- `s`: global dictionary search
- `:`: command line
- `!`: shell/terminal
- `?`: help for current menu/tool

## EDITOR

- Browse `system/`, `constant/`, and `0*` files
- Entry preview shows type, value, comments, and boundary info
- Values are validated (dimensions, fields, vectors, etc.)
- `e`/`Enter` to edit; `v` to view file; `o` to open `$EDITOR`

## STAGES AND COMMAND MODE

Common actions are grouped under Mesh, Physics, Simulation, Post‑Processing,
Clean case, and Config Manager. Actions are disabled with a clear reason when
required files/environment are missing.

Command mode shortcuts:
- `:tool <name>` or `:<name>` runs tool aliases/presets.
- `:run ...`, `:knife ...`, `:watch ...`, `:plot ...` call non-interactive CLI.

Post‑Processing notes:
- `View logs` contains file view, live tail, and log analysis summary.
- `PostProcessing tables` loads table-like outputs using foamlib postprocessing extras.
- `Sampling & sets` includes `postProcess`-driven sampling actions.
- `Parametric wizard` supports single-entry, CSV, and grid studies (when preprocessing extras are installed).

## PARAMETRIC STUDIES

CLI and TUI now share the same foamlib-backed generation paths:

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

## FILES

- Case root with `system/controlDict`
- Optional presets: `ofti.parametric`
- Logs: `log.*`
- Config: `~/.config/ofti/config.toml` (or `$OFTI_CONFIG`)

## LICENSE

GPL-3.0-or-later.

 
