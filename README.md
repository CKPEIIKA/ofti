# of_tui – OpenFOAM TUI

`of_tui` is a small curses-based tool to browse and edit OpenFOAM case dictionaries.

> Disclaimer: this project has been “vibe coded” and is under active, heavy development. Expect rough edges, rapid changes, and incomplete features; contributions and bug reports are very welcome.

## Usage

1. Source your OpenFOAM environment so `foamDictionary` (and other foam* tools) are on `PATH`.
2. Run on a case folder (the example case is in `of_example`):

   ```bash
   ./of_tui of_example
   ```

   You can also run it in the current directory:

   ```bash
   of_tui .
   ```

3. Optional flags:

   - `--debug` – enable debug logging and let unexpected errors surface with a traceback.

## Main navigation

- `j` / `k` or arrows: move up/down in menus and lists
- `l` or `Enter`: select
- `h` or `q`: go back / quit (on the root menu, only `q` quits)
- `/` in menus: fuzzy-pick an option with `fzf` (when available)

Main menu entries:

- `Editor` – browse `system`, `constant`, and `0*` dictionaries and edit entries.
- `Check syntax` – run a simple `foamDictionary`-based check over all discovered dictionaries.
- `Tools` – run common solvers/utilities, job helpers, and view logs.
- `Diagnostics` – run `foamSystemCheck`, `foamInstallationTest`, `checkMesh`, `foamCheckMesh`.
- `Global search` – (shown only when `fzf` is available) search across all keys with `fzf` and jump to the chosen entry.

## Editor and entry browser

- In the editor, pick a section (`system`, `constant`, `0*`), then a file, then an entry.
- Left pane: list of keys; right pane: preview of the selected entry (key path, type, value, comments, info).
- Status bar: shows case name, file, and full key path.

Keybindings in the entry browser:

- `j` / `k` or arrows: move between entries
- `l` / `Enter` / `e`: edit the current entry
- `h` / `Left` / `q`: go back (or up one dictionary level)
- `v`: view the full file
- `o`: open the current entry in `$EDITOR` and write back on save
- `/`: search entries with `fzf` (when available), otherwise simple in-file search
- `n` / `N`: repeat last in-file search forward/backward

Keybindings in the entry editor:

- Arrow keys: move the cursor in the input line
- `Backspace`: delete at the cursor
- `Enter`: save the new value (with validation and a confirmation prompt if the value looks dangerous)
- `Ctrl+C` or `b`: cancel editing
- `h`: run `foamHelp` with user-provided arguments and show the result in a viewer

Values are auto-formatted conservatively on save (e.g. trimming trailing newlines and leading/trailing spaces on simple scalars) before being written back with `foamDictionary -set`.

## Tools and diagnostics

- `Tools → Run tools`:
  - `blockMesh`, `decomposePar`, `reconstructPar`, `foamListTimes`
  - Extra tools can be defined in `of_tui.tools` (one `name: command` per line) in the case directory.
  - `foamCheckJobs`, `foamPrintJobs`
  - `foamJob` – prompt for arguments (e.g. `simpleFoam -case .`) and run it
  - `foamEndJob` – prompt for arguments (e.g. `simpleFoam`) and run it
  - `View logs` – pick a `log.*` file and either view the full log or only the last 100 lines
  - `Run .sh script` – discover and run `*.sh` scripts in the case directory
- `Diagnostics`:
  - `foamSystemCheck`, `foamInstallationTest`
  - `checkMesh`

All tool runs show a summary with the command, exit status, stdout, and stderr in a scrollable viewer.

## Repository layout

- `of_tui` – CLI entry script (used as `./of_tui` or installed as `of_tui`).
- `tui/` – main Python package:
  - `app.py` – entry point and main loop.
  - `editor.py` – entry editor and viewer components.
  - `menus.py` – generic menus and keybindings.
  - `openfoam.py` – wrappers around OpenFOAM utilities (foamDictionary, etc.).
  - `tools.py` – tools, jobs, and diagnostics screens.
- `tests/` – pytest-based test suite.
- `of_example/` – small example OpenFOAM case for experimentation.
- `TODO.md` – roadmap of remaining P2/P3 items.

## Development

Requirements:

- Python 3.11+ (tested with 3.11).
- `pytest` for running tests.
- A working OpenFOAM environment for runtime usage (for tests that touch OpenFOAM, see the optional integration test).

Run tests:

```bash
pytest
```

You can work directly from a clone of this repository; no packaging or installation step is required beyond making `of_tui` executable or calling it with:

```bash
python ./of_tui
```
