# OFTI Engineering Philosophy

This repository follows a pragmatic "suckless" approach:
small, composable tools; clear layering; and Unix-style CLI behavior.

## Core principles

- OFTI is a convenience wrapper around `foamlib`, not a parallel OpenFOAM stack.
- Prefer `foamlib` APIs first; keep fallbacks minimal, generic, and reusable.
- Keep logic shared between interfaces: CLI and TUI must call the same core/services.
- Keep adapters thin: parsing, dispatch, formatting, exit-code mapping only.
- Avoid case-specific hacks in generic tooling.

## Layering rules

- `ofti/foamlib` is the only layer that imports upstream `foamlib` directly.
- `ofti/core` holds pure domain/file logic: no curses, no UI, and no raw
  subprocess. Core reaches OpenFOAM tools only through the `ofti/foam`
  trusted-subprocess boundary (`run_trusted`); this is enforced by
  `tests/test_architecture_boundaries.py`.
- `ofti/foam` owns OpenFOAM environment discovery and the trusted subprocess
  boundary; `ofti/tools` holds reusable case services shared by CLI and TUI.
- `ofti/app/cli_adapters/*`, `ofti/app/cli_tools.py`, and `ofti/tools/cli_tools/*`
  are the CLI adapters; `ofti/app`, `ofti/ui`, `ofti/ui_curses`, `ofti/ui_textual`
  are the TUI adapters. Adapters parse input, call services, and render output.
- TUI flows should reuse the same service/core functions as CLI commands.
- If logic is needed by more than one command/screen, move it out of UI layer.
- Oversized service modules use the facade pattern (a canonical module that
  re-exports cohesive sibling modules); see `docs/layering.md`.

## CLI command & plugin API

- Commands are described as framework-neutral specs in
  `ofti/core/command_spec.py` (`CommandSpec`/`ArgumentSpec`/`OptionSpec`); the
  argparse adapter `ofti/app/cli_adapters/command_builder.build_spec_parser`
  builds parsers from them. Plugins declare `command_spec()` and never touch
  argparse.
- Machine output is stamped through the shared output contract
  `ofti/core/output_contract.py` (`stamp_payload`/`command_name`), so every
  `--json` object carries a `schema_version` and the `command` that produced it
  — for core and plugin commands alike.
- Plugins register through `ofti/plugins.py` (`PluginRegistry`) via the
  `ofti.plugins` entry-point group; registration refuses to overwrite an
  existing preset/profile/command name.

## Unix-way CLI expectations

- Commands should be short, scriptable, and predictable.
- Human-readable output is concise by default.
- `--json` is optional machine output for automation.
- Help text (`-h/--help`) should be complete and practical.
- Exit codes are reliable (0 success, non-zero failure).

## Suckless implementation style

- Favor simple data flow and explicit behavior over hidden magic.
- Reuse existing routines before adding new abstractions.
- Keep dependencies minimal and justified.
- Prefer small functions with clear ownership.

## Performance and reliability

- Large-file workflows (especially logs) must remain responsive.
- Use bounded reads/tail windows for heavy logs by default.
- Fail per-file/per-step when possible; continue with useful partial results.

## Quality gates

- Keep `ruff`, `ty`, and full `pytest` green.
- Maintain coverage gate at current project target (>=85%).
- Add tests for shared services first; adapter tests focus on wiring/output.

## Safety and hygiene

- No personal data or hardcoded local paths in committed code/docs.
- Keep defaults generic and portable.
- Document user-facing behavior changes in `README.md` and command help.
