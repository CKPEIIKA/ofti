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
- `Enter` selects; `h` / `Esc` go back; `q` quits OFTI from any screen;
  `?` opens contextual help.
- `e` edits an entry, `v` views a file, and `o` opens `$EDITOR` where supported.
- `:tool NAME` or `:NAME` invokes a tool preset; `:run` / `:solver` start the
  case solver and `:run NAME` runs a tool preset.
- `:knife ...`, `:watch ...`, and `:plot ...` run the same argparse adapters as
  `ofti knife|watch|plot ...` in a child process whose working directory is the
  case, so the CASE argument may be omitted (`:knife status`). Output stays on
  the terminal until Enter; Ctrl-C stops a long `watch` follow.
- `!CMD` / `:term CMD` run a shell command in the case directory and wait for
  Enter; a bare `!` opens `$SHELL`.

Viewers (overview, logs, command output) scroll with `j`/`k` or arrows,
`PgDn`/`Space` and `PgUp`/`b`, `g`/`G` or `Home`/`End`, and sideways with
`Left`/`Right` or `<`/`>`. The top line shows the visible line range; `/`
searches forward and wraps. Log files open at their tail.

The case header is re-read after every menu action or command, reports
`Env: not loaded` when no OpenFOAM environment is active, and treats a solver
log that ended with `End` as finished even while it is still fresh.

Terminal behavior is covered by deterministic fake-screen tests. Reusable
OpenFOAM logic belongs in `ofti/core`, `ofti/foam`, or `ofti/tools`, never in a
screen.
