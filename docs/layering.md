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
   - `ofti/core`: pure domain/file logic; no curses, no UI, and no raw
     subprocess. The few core services that need an OpenFOAM tool (run-manifest
     provenance, pipeline run, dict-generation fallback) reach it only through
     the `ofti/foam` trusted-subprocess boundary (`run_trusted`); core never
     imports `subprocess` directly. Filesystem-only time discovery lives in
     `ofti/core/times`; OpenFOAM-assisted `latest_time` (foamListTimes) lives in
     `ofti/foam/times`. Enforced by `tests/test_architecture_boundaries.py`.
   - `ofti/foam`: OpenFOAM environment discovery and trusted subprocess
     boundary.
   - `ofti/tools`: reusable case services shared by CLI and TUI.
   - May use `ofti/foamlib`; must not duplicate capabilities that `foamlib`
     covers reliably.

3. CLI adapter: `ofti/app/cli_tools.py`, `ofti/app/cli_adapters/*`,
   `ofti/tools/cli_tools/*`
   - `cli_adapters/main.py` owns top-level parsing and dispatch;
     command-group adapters own their handlers; `tools/cli_tools/*` owns
     reusable service calls; `cli_help.py` and table render services own
     presentation.
   - `cli_tools.py` is only the stable legacy import path for `main`,
     `build_parser`, and `ofti_version`; it does not re-export private handlers
     or service modules.
   - Argparse, dispatch, output modes, exit-code mapping, and help text.
   - Calls OFTI library services.
   - Does not parse OpenFOAM files or implement case management directly.
   - Builds parsers from framework-neutral `CommandSpec`s where commands are
     declared as specs (`ofti/app/cli_adapters/command_builder.build_spec_parser`);
     argparse stays an adapter detail. See "Plugin command specs" below.

### CLI compatibility surface

The former `cli_tools.py` namespace copier was audited and removed:

- public API: `main`, `build_parser`, and `ofti_version` remain explicit,
  supported imports;
- internal dependencies: command-group handlers stay in their
  `cli_adapters/<group>.py` modules;
- compatibility-only aliases: service modules and private handler aliases are
  no longer exported because they were undocumented implementation details;
- test hooks: tests patch the explicit adapter dependency (`run_ops`,
  `watch_ops`, `knife_ops`, or a named adapter function) rather than rebinding a
  hidden `cli_tools` namespace.

`tests/test_architecture_boundaries.py` rejects dynamic namespace calls and
private adapter imports in the compatibility module.

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

## Service facade pattern

Large service modules are kept under ~1000 lines by extracting cohesive
clusters into sibling modules while the original stays the canonical surface
that re-exports them (e.g. `knife_service` + `knife_process`/`knife_campaign`/
`knife_runtime`/`knife_analysis`/`knife_stop`; `runtime_control_service` + `runtime_criteria`;
`watch_service` + `watch_external`; `cli_tools/run` + `run_smoke`/`run_queue`;
`cli_adapters/knife` + `knife_parser`). Conventions:

- The facade re-exports moved names via module-alias assignment
  (`x = _sibling.x`) when they are not used internally, so ruff does not prune
  them and tests/adapters keep one import surface.
- When an extracted sibling must call back into a function that stays in the
  facade (or is monkeypatched on it), it uses a lazy accessor
  (`def _svc(): from ... import facade; return facade`) instead of a top-level
  import. This breaks the import cycle and preserves `facade.name`
  monkeypatch behavior at call time.
- Shared module objects (`os`, `subprocess`, service modules) are imported
  normally in siblings; tests patch attributes on the shared object, so those
  patches still apply.

## Plugin command and progress specs

CLI commands — including plugin-provided `knife`, `run`, `watch`, and `result`
commands — are described as
framework-neutral specs in `ofti/core/command_spec.py` (`CommandSpec`,
`ArgumentSpec`, `OptionSpec`), which know nothing about argparse. The argparse
adapter `ofti/app/cli_adapters/command_builder.build_spec_parser` turns a spec
into a subparser; a future Click/Typer adapter would consume the same specs.

- A plugin command class exposes `command_spec(self) -> CommandSpec` (naming its
  positional arguments, options, and `handler`) instead of touching argparse.
  The group adapters build these specs through one explicit command builder.
- Plugin handlers emit machine output through the shared output contract
  (`ofti/core/output_contract.stamp_payload` + `command_name`), so plugin
  `--json` carries the same `schema_version`/`command` envelope as core
  commands. Core CLI output (`cli_help.emit_json`) routes through the same
  contract, keeping one JSON shape across core and plugins.
- A progress provider implements a read-only
  `progress_metrics(case_dir, *, log_path=None)` method. Status services attach
  its namespaced mapping under `plugin_metrics`; one failed provider is exposed
  under `plugin_metric_errors` without hiding core evidence.
- `ofti plugins list|doctor` exposes entry-point source, distribution/version,
  registrations, and load failures. Discovery errors never become silent
  fallbacks.
- Plugins register into the registry passed through parser construction. Core
  never imports a solver-family plugin, and plugins never reach into argparse
  or UI internals.

## Rules of thumb

- Add a new module only when it has clear ownership and prevents duplication.
- Avoid facade packages and "manager" classes; the service-facade split above
  is the sanctioned exception for oversized single modules.
- Prefer small functions and explicit data flow.
- Keep UI code dumb: format and display data, do not parse OpenFOAM files.
- Keep adapters thin: parse arguments/input, call library functions, render
  output, return stable exit codes.
