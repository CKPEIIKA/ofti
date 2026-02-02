# ofti – OpenFOAM Terminal Interface

```
  ____  ______ _______ _____
 / __ \\ |  ___|__   __|_   _|
| |  | | |__     | |    | |
| |  | |  __|    | |    | |
| |__| | |       | |   _| |_
 \\____/|_|      |_|  |_____|
```

`ofti` (OpenFOAM Terminal Interface) is a small curses-based TUI for browsing and editing OpenFOAM case dictionaries, with built-in tools and diagnostics.

Disclaimer: this is vibe-coded software! Under severe development!

License: GPL-3.0-or-later.

## Quick start

1. Source your OpenFOAM environment so openfoam tools are on `PATH`.
2. Run against a case:

   ```bash
   python -m ofti.app.cli /path/to/case
   ```

   Or install and use the console script:

   ```bash
   pip install .
   ofti /path/to/case
   ```

   If the provided path is not an OpenFOAM case, `ofti` opens a simple folder picker to choose a valid case directory.

3. Optional flags:

   - `--debug` – enable debug logging and let unexpected errors surface with a traceback.

## Navigation

- `j` / `k` or arrows: move up/down in menus and lists
- `l` or `Enter`: select
- `h` or `q`: go back / quit (on the root menu, only `q` quits)
- `/` in menus: fuzzy-pick an option with `fzf` (when available)
- `s` in menus: config search (global `fzf` search over keys)
- `:` in menus: open the command line (`:check`, `:tools`, `:diag`, `:run`, `:quit`)
- `:tool <name>` or `:<name>` to run any tool entry from the Tools menu
- `Tab` in the command line auto-completes (cycles) matching commands

Main menu entries (grouped):

- `Mesh` – blockMesh, checkMesh, decompose, reconstruct.
- `Physics & Boundary Conditions` – config editor, check syntax, dictionary linter.
- `Simulation` – run solver, safe stop, resume.
  - Solver status shows whether the live runner is busy or last exit failed.
- `Post-Processing` – reconstruct manager, time pruning, logs, postProcess/foamCalc.
- `Config Manager` – config editor + config search.
- `Tools / Diagnostics` – uncategorized tools and diagnostics.

The header banner shows case info, solver, OpenFOAM version, case header version, latest time, mesh/parallel summary, and path.

## Editor and entry browser

- In the editor, pick a section (`system`, `constant`, `0*`), then a file, then an entry.
- Left pane: list of keys; right pane: preview of the selected entry (key path, type, value, comments, info).
- Status bar: shows case name, file, and full key path.
- When browsing `boundaryField` entries, the preview shows the detected boundary-condition type and value (via foamlib).

Keybindings in the entry browser:

- `j` / `k` or arrows: move between entries
- `l` / `Enter` / `e`: edit the current entry
- `h` / `Left` / `q`: go back (or up one dictionary level)
- `v`: view the full file
- `o`: open the current entry in `$EDITOR` and write back on save
- `/`: search entries with `fzf` (when available), otherwise simple in-file search
- `:`: open the command line (`:check`, `:tools`, `:diag`, `:run`, `:quit`)
- `:tool <name>` or `:<name>` to run any tool entry from the Tools menu
- `Tab` in the command line auto-completes (cycles) matching commands

Keybindings in the entry editor:

- Arrow keys: move the cursor in the input line
- `Backspace`: delete at the cursor
- `Enter`: save the new value (with validation and a confirmation prompt if the value looks dangerous)
- `Ctrl+C` or `b`: cancel editing
- `h`: run `foamHelp` with user-provided arguments and show the result in a viewer

Values are auto-formatted conservatively on save (e.g. trimming trailing newlines and leading/trailing spaces on simple scalars) before being written back with foamlib. The editor also surfaces extra metadata and boundary-condition summaries where available.

## Tools and diagnostics

- `Tools`
  - Built-in entries for `blockMesh`, `decomposePar`, `reconstructPar`, `setFields`, and common utilities.
  - Extra commands can be added via `ofti.tools`; optional post-processing commands live in `ofti.postprocessing` and appear prefixed with `[post]`.
  - `postProcess` and `foamCalc` capture arguments interactively, defaulting to `-latestTime` when it makes sense; they require `system/postProcessDict` and `system/foamCalcDict` and are disabled until those configs exist.
  - `Run current solver (runApplication)` sources `$WM_PROJECT_DIR/bin/tools/RunFunctions` and runs the solver declared in `system/controlDict`.
  - Cleanup helpers (`Remove all logs`, `Clean time directories`, `Clean case`) source `$WM_PROJECT_DIR/bin/tools/CleanFunctions`.
  - `topoSet (prompt)` and `setFields (prompt)` run common setup utilities.
  - `Run shell script` discovers shell scripts in the case directory.
  - Prefix either the `:tool <name>` command or the tool name itself with `-b` (e.g., `:tool blockMesh -b` or `blockMesh -b`) to start that tool as a background job; the `Job status` entry shows active jobs.
  - Any entry from `ofti.tools`/`ofti.postprocessing` can use the placeholder `{{latestTime}}` which expands to the numerically largest time directory.
- `Diagnostics`:
  - `foamSystemCheck`, `foamInstallationTest`, `checkMesh`
  - `View logs` – pick a `log.*` file and view the full log

## Case report

`ofti.core.case_report.collect_case_report` gathers mesh counts, face/point totals, and boundary patch breakdowns without running OpenFOAM binaries. The data drives the dashboard header and gives a quick health check of the case (cells/faces/points, number of patches per type, etc.).

All tool runs show a summary with the command, exit status, stdout, and stderr in a scrollable viewer.

## Repository layout

- `ofti/` – Python package that provides the CLI (`ofti.app.cli:main`) and all runtime modules:
  - `app/` – top-level app flow, screens, command handling.
  - `ui_curses/` – curses UI widgets and screens.
  - `core/` – parsing + case helpers, UI-agnostic logic.
  - `foam/` – OpenFOAM environment and tool wrappers (run helpers, config, subprocess, tasks).
  - `tools/` – tools/diagnostics implementations.
- `tests/` – pytest suite (unit + optional integration).
- `of_example/` – small example OpenFOAM case for experimentation.

## Layering rules (keep it simple)

- `core` is pure logic: no curses, no UI imports, no shell execution.
- `foam` owns OpenFOAM env + subprocess calls; it must not import `ui` or `ui_curses`.
- `ui` is a thin adapter/router; it must not import `ui_curses`.
- `ui_curses` renders screens and calls into `core`/`foam` via small helpers.
- Add new modules only when reused in 2+ places; prefer small helpers in existing files.

## Development

Requirements:

- Python 3.11+ (tested with 3.11).
- `foamlib==1.5.5` for OpenFOAM dictionary parsing/writing.
- `pytest` for running tests.
- A working OpenFOAM environment for runtime usage (for tests that touch OpenFOAM, see the optional integration test).
- Coverage target: 70% minimum (pytest-cov).
- Optional config file: `~/.config/ofti/config.toml` (or `$OFTI_CONFIG`).
