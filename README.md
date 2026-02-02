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

## DESCRIPTION

`ofti` is a small curses-based interface for OpenFOAM cases. It focuses on
fast browsing/editing of dictionaries, a boundary/initial-conditions view,
and common tools (mesh, run, post-process, diagnostics).

If the provided path is not an OpenFOAM case, `ofti` opens a folder picker
to select a valid case directory.

## REQUIREMENTS

- Python 3.11+
- `foamlib` (dictionary parsing/writing)
- OpenFOAM environment on `PATH` for running tools (optional for read-only)

## MODES

- **Normal**: OpenFOAM environment detected; tools available.
- **Limited**: OpenFOAM env not detected; tools are disabled, editor remains usable.

## KEYS (GLOBAL)

- `j/k` or arrows: move
- `Enter`: select
- `h` or `Esc`: back
- `q`: quit (root menu only)
- `/`: menu search with `fzf` (if installed)
- `s`: config search (global)
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

## FILES

- Case root with `system/controlDict`
- Optional presets: `ofti.parametric`
- Logs: `log.*`
- Config: `~/.config/ofti/config.toml` (or `$OFTI_CONFIG`)

## LICENSE

GPL-3.0-or-later.

## DISCLAIMER

This is vibe-coded software. Expect rough edges.
