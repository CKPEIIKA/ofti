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

- `ofti/core` and shared service modules hold domain logic.
- `ofti/tools/cli_tools/*` and `ofti/app/cli_tools.py` are interface adapters.
- TUI flows should reuse the same service/core functions as CLI commands.
- If logic is needed by more than one command/screen, move it out of UI layer.

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
- Maintain coverage gate at current project target (>=75%).
- Add tests for shared services first; adapter tests focus on wiring/output.

## Safety and hygiene

- No personal data or hardcoded local paths in committed code/docs.
- Keep defaults generic and portable.
- Document user-facing behavior changes in `README.md` and command help.
