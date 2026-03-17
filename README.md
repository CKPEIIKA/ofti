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
   Tools
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
ofti watch jobs CASE --json
ofti watch pause CASE --all
ofti watch resume CASE --all
ofti watch stop CASE --signal TERM
ofti watch log CASE --lines 80 --json
ofti run tool --list --case CASE --json
ofti run solver CASE --dry-run --json
ofti run matrix CASE --param application=simpleFoam,pisoFoam --no-launch --json
ofti run queue --set CASE_SET --glob 'case_*' --max-parallel 6 --json
ofti run status --set CASE_SET --fast --json
```

For very large logs, analysis/tail commands read recent log windows to stay
responsive.

External watcher integration (for example `scripts/oftools/ofwatch`) is
expected to run through tool presets in `ofti.tools` and can be executed with
`ofti run tool <name> --case CASE`.

## REQUIREMENTS

- Python 3.10+
- `foamlib` (dictionary parsing/writing)
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

## TOOLS

Common actions are grouped under Mesh, Physics, Simulation, Post‑Processing,
Config Manager, and Tools/Diagnostics. Tools are greyed out when required
configs are missing. `:tool <name>` or `:<name>` runs any tool entry.

Post‑Processing notes:
- `View logs` contains file view, live tail, and log analysis summary.
- `Sampling & sets` includes `postProcess`-driven sampling actions.
- `Parametric wizard` can load presets from `ofti.parametric` or run manual sweeps.

## FILES

- Case root with `system/controlDict`
- Optional presets: `ofti.parametric`
- Logs: `log.*`
- Config: `~/.config/ofti/config.toml` (or `$OFTI_CONFIG`)

## LICENSE

GPL-3.0-or-later.

 
