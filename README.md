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

Disclaimer: this is vibe-coded software! Use with care!

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
   - `--no-foam` – skip OpenFOAM tool usage (view-only mode; tools may fail with a hint).

## Navigation

- `j` / `k` or arrows: move up/down in menus and lists
- `l` or `Enter`: select
- `h` or `q`: go back / quit (on the root menu, only `q` quits)
- `/` in menus: fuzzy-pick an option with `fzf` (when available)
- `s` in menus: config search (global `fzf` search over keys)
- `:` in menus: open the command line (`:check`, `:tools`, `:diag`, `:run`, `:quit`)
- `:nofoam` to toggle no-foam mode on/off
- `:tool <name>` or `:<name>` to run any tool entry from the Tools menu
- `Tab` in the command line auto-completes (cycles) matching commands

Main menu entries (grouped):

- `Pre-Processing (Mesh)` – blockMesh, checkMesh, decompose, reconstruct.
- `Physics & Boundary Conditions` – config editor, check syntax, dictionary linter.
- `Simulation (Run)` – run solver, safe stop, resume, foamJob helpers.
- `Post-Processing` – reconstruct manager, time pruning, logs, postProcess/foamCalc.
- `Config Manager` – config editor + config search.
- `Tools / Diagnostics` – uncategorized tools and diagnostics.

The header banner shows case info, solver, OpenFOAM version, case header version, latest time, mesh/parallel summary, and path.

## Editor and entry browser

- In the editor, pick a section (`system`, `constant`, `0*`), then a file, then an entry.
- Left pane: list of keys; right pane: preview of the selected entry (key path, type, value, comments, info).
- Status bar: shows case name, file, and full key path.
- When browsing `boundaryField` entries, the preview automatically shows the detected boundary-condition type and value (queried via `foamDictionary`).

Keybindings in the entry browser:

- `j` / `k` or arrows: move between entries
- `l` / `Enter` / `e`: edit the current entry
- `h` / `Left` / `q`: go back (or up one dictionary level)
- `v`: view the full file
- `o`: open the current entry in `$EDITOR` and write back on save
- `/`: search entries with `fzf` (when available), otherwise simple in-file search
- `:`: open the command line (`:check`, `:tools`, `:diag`, `:run`, `:quit`)
- `:nofoam`: toggle no-foam mode on/off
- `:tool <name>` or `:<name>` to run any tool entry from the Tools menu
- `Tab` in the command line auto-completes (cycles) matching commands
- In no-foam mode, file browsing offers "Open in $EDITOR" for quick edits without foamDictionary.

Keybindings in the entry editor:

- Arrow keys: move the cursor in the input line
- `Backspace`: delete at the cursor
- `Enter`: save the new value (with validation and a confirmation prompt if the value looks dangerous)
- `Ctrl+C` or `b`: cancel editing
- `h`: run `foamHelp` with user-provided arguments and show the result in a viewer

Values are auto-formatted conservatively on save (e.g. trimming trailing newlines and leading/trailing spaces on simple scalars) before being written back with `foamDictionary -set`. The editor also surfaces extra metadata gathered from `foamDictionary -info/-list` (enum values, required sub-entries) plus boundary-condition summaries for `boundaryField`.

## Tools and diagnostics

- `Tools`
  - Built-in entries for `blockMesh`, `decomposePar`, `reconstructPar`, `foamListTimes`, `foamCheckJobs`, `foamPrintJobs`, and the `foamJob` / `foamEndJob` helpers.
  - Extra commands can be added via `ofti.tools`; optional post-processing commands live in `ofti.postprocessing` and appear prefixed with `[post]`.
  - `postProcess (prompt)` and `foamCalc (prompt)` capture arguments interactively, defaulting to `-latestTime` when it makes sense.
  - `Run current solver (runApplication)` sources `$WM_PROJECT_DIR/bin/tools/RunFunctions` and runs the solver declared in `system/controlDict`.
  - Cleanup helpers (`Remove all logs`, `Clean time directories`, `Clean case`) source `$WM_PROJECT_DIR/bin/tools/CleanFunctions`.
  - `Run .sh script` discovers shell scripts in the case directory; `foamDictionary (prompt)` offers an escape hatch for arbitrary queries.
  - Any entry from `ofti.tools`/`ofti.postprocessing` can use the placeholder `{{latestTime}}` which expands to the numerically largest time directory.
- `Diagnostics`:
  - `foamSystemCheck`, `foamInstallationTest`, `checkMesh`
  - `View logs` – pick a `log.*` file and either view the full log or just the last 100 lines

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

## Development

Requirements:

- Python 3.11+ (tested with 3.11).
- `pytest` for running tests.
- A working OpenFOAM environment for runtime usage (for tests that touch OpenFOAM, see the optional integration test).
- Coverage target: 70% minimum (pytest-cov).
- Optional config file: `~/.config/ofti/config.toml` (or `$OFTI_CONFIG`).

Run tests:

```bash
pytest
```

Example config:

```toml
fzf = "auto" # auto | on | off
use_runfunctions = true
use_cleanfunctions = true
enable_entry_cache = true
enable_background_checks = true
enable_background_entry_crawl = false

[colors]
focus_fg = "black"
focus_bg = "cyan"

[keys]
up = ["k"]
down = ["j"]
select = ["l", "\n"]
back = ["h", "q"]
help = ["?"]
command = [":"]
search = ["/"]
top = ["g"]
bottom = ["G"]
```
