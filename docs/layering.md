# Layering and simplicity rules

OFTI is built as a small library plus thin adapters:

```text
foamlib adapter + OFTI library -> CLI adapter
                            \-> TUI adapter
```

This is an architecture decision, not a facade package. New code should make the
data path obvious: use upstream `foamlib` through `ofti/foamlib`, implement OFTI
behavior in reusable library modules, and keep CLI/TUI code as adapters.

## Layers

1. `ofti/foamlib`
   - The only layer that imports upstream `foamlib` directly.
   - Translates `foamlib` objects into plain OFTI values.
   - Provides stable dictionary, field, post-processing, clone, and runner
     operations.
   - Keeps fallback parsing generic and small when `foamlib` cannot cover a
     case.

2. OFTI library: `ofti/core`, `ofti/foam`, `ofti/tools`
   - `ofti/core`: pure domain/file logic; no curses, no UI, no OpenFOAM process
     execution.
   - `ofti/foam`: OpenFOAM environment discovery and trusted subprocess
     boundary.
   - `ofti/tools`: reusable case services shared by CLI and TUI.
   - May use `ofti/foamlib`; must not duplicate capabilities that `foamlib`
     covers reliably.

3. CLI adapter: `ofti/app/cli_tools.py`, `ofti/app/cli_adapters/*`,
   `ofti/tools/cli_tools/*`
   - Argparse, dispatch, output modes, exit-code mapping, and help text.
   - Calls OFTI library services.
   - Does not parse OpenFOAM files or implement case management directly.

4. TUI adapter: `ofti/app`, `ofti/ui`, `ofti/ui_curses`
   - Flow, prompts, layout, rendering, key bindings.
   - Calls OFTI library services.
   - Does not own OpenFOAM parsing or process logic.

## Test split

- Fast unit tests cover library and adapter behavior with fixtures/mocks.
- Slow real OpenFOAM tests use `@pytest.mark.slow` and run only with
  `pytest --runslow`.
- Real OpenFOAM tests should grow toward critical end-to-end flows:
  discover/adopt runs, live writeNow, stop/resume, parallel resize, runtime
  dictionary reread, cleanup, and replay/report artifacts.

## Declared debt

The current enforced target is no UI imports below adapters, no CLI-adapter
imports below adapters, and no direct upstream `foamlib` imports outside
`ofti/foamlib`. The explicit allowlists in
`tests/test_architecture_boundaries.py` are empty; new code must keep them
empty.

## Rules of thumb

- Add a new module only when it has clear ownership and prevents duplication.
- Avoid facade packages and "manager" classes.
- Prefer small functions and explicit data flow.
- Keep UI code dumb: format and display data, do not parse OpenFOAM files.
- Keep adapters thin: parse arguments/input, call library functions, render
  output, return stable exit codes.
