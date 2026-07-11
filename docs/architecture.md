# OFTI Architecture

OFTI is a convenience layer around OpenFOAM and `foamlib`. The codebase is
structured so the CLI and TUI share the same case services instead of growing
parallel implementations.

## Layer graph

Allowed dependency direction:

```text
app/cli_adapters  app/menus app/screens
        |              |
        v              v
      tools / shared services
        |       |       |
        v       v       v
      core    foam    foamlib
        |
        v
    stdlib / filesystem-only helpers

ui_curses is a concrete renderer used by app screens.
ui is UI-neutral contracts/helpers.
```

## Packages

- `ofti/foamlib/`: optional `foamlib` integration. It may import `foamlib` and
  generic fallbacks. It must not import `ofti.app`, `ofti.ui`, or
  `ofti.ui_curses`.
- `ofti/foam/`: OpenFOAM process, environment, and trusted subprocess boundary.
  Shell/OpenFOAM command execution belongs here or in services that deliberately
  call this layer.
- `ofti/core/`: pure case/domain logic. It should use filesystem parsing and
  value transformations only. It must not import `subprocess`, `ofti.app`,
  `ofti.ui`, `ofti.ui_curses`, or OpenFOAM command runners.
- `ofti/tools/`: shared application services used by CLI and TUI. Services may
  call `core`, `foam`, and `foamlib`. Services must not import `ofti.app` or
  concrete UI modules.
- `ofti/app/cli_adapters/`: argparse and CLI output adapters by command group.
  These modules parse arguments, map exit codes, and render human/JSON/table
  output. Domain behavior belongs in `ofti/tools`.
- `ofti/app/cli_tools.py`: compatibility dispatcher for legacy imports and the
  public CLI entrypoint. New command wiring belongs in `ofti/app/cli_adapters`.
- `ofti/app/menus/` and `ofti/app/screens/`: TUI flow controllers. They prompt,
  dispatch to services, render screens, and handle keys.
- `ofti/ui/`: UI-neutral contracts/helpers.
- `ofti/ui_curses/`: concrete curses widgets, layout, and rendering primitives.

## Rules

1. CLI and TUI must reuse shared service functions for behavior.
2. UI modules are adapters: prompt, dispatch, display, keybinding, and error
   presentation only.
3. Services return structured payloads. Rendering belongs in CLI/TUI adapters or
   explicit render helpers such as table renderers.
4. `core` stays free of OpenFOAM subprocess execution.
5. Prefer `foamlib` APIs where they are stable and reduce custom parsing.
6. Heavy log and case scans must be bounded by default in UI paths.
7. CLI output modes are stable: plain by default, `--table` for structured human
   diagnostics, `--json` for automation; `--json` and `--table` are mutually
   exclusive.

## Near-term cleanup targets

- Keep `ofti/app/cli_tools.py` as a thin compatibility shim; do not add command
  implementation bodies there.
- Move Captains Deck aggregation out of `ofti/app/overview.py` into shared
  services.
- Keep `ofti/core/times.py` filesystem-only; OpenFOAM-assisted time lookup lives
  in `ofti/foam/times.py`.
- Run receipt logic currently lives in `ofti/core/run_receipt.py`; CLI adapters
  expose it as the stable user-facing `receipt` workflow until a manifest rename
  is implemented as a real migration.
