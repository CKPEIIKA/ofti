# Curses interface

Running `ofti CASE` on a real terminal opens the curses interface. Running
without a valid case first opens a case chooser. `--plain` / `--no-tty`
guarantees that curses is never entered; a headless bare invocation fails with
exit code 2 and a concise diagnostic.

The TUI is an adapter over the same services as the CLI. It provides:

- a read-only Overview with case status, tracked/live processes, criteria, ETA,
  log metrics, and residual summaries;
- dictionary and entry browsing for `system/`, `constant/`, and time-zero
  fields;
- boundary and initial-condition views;
- Mesh, Physics, Simulation, Post-Processing, Clean case, and Config menus;
- command mode for invoking shared `run`, `knife`, `watch`, and `plot`
  operations.

OpenFOAM-dependent actions are disabled with a reason when the environment or
required files are unavailable. Dictionary browsing remains available in
limited mode.

## Keys and editor

- `j` / `k` move through menus and lists.
- `Enter` selects; `q` returns or quits; `?` opens contextual help.
- `e` edits an entry, `v` views a file, and `o` opens `$EDITOR` where supported.
- `:tool NAME` or `:NAME` invokes a tool preset.
- `:run ...`, `:knife ...`, `:watch ...`, and `:plot ...` invoke the same
  non-interactive adapters used by the CLI.

Terminal behavior is covered by deterministic fake-screen tests. Reusable
OpenFOAM logic belongs in `ofti/core`, `ofti/foam`, or `ofti/tools`, never in a
screen.
