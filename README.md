# OFTI(1)

```text
  ____  ______ _______ _____
 / __ \ |  ___|__   __|_   _|
| |  | | |__     | |    | |
| |  | |  __|    | |    | |
| |__| | |       | |   _| |_
 \____/|_|      |_|  |_____|
```

## DISCLAIMER

This project is vibe-coded. Expect rough edges and verify behavior before
using it on production OpenFOAM cases.

OFTI is a CLI-first OpenFOAM helper with a curses interface on top. It wraps
`foamlib` and native OpenFOAM tools for diagnostics, run/process management,
safe parallel resume, queues, field checks, portable bundles, result packs, and
reproducibility manifests. CLI and TUI adapters reuse the same services.

## Install

Python 3.11 or newer is required. From a checkout:

```bash
uv tool install .
# Development environment:
uv sync --locked --group dev
```

OFTI is not published on PyPI. Install a tagged release from GitHub:

```bash
uv tool install "git+https://github.com/CKPEIIKA/ofti.git@vX.Y.Z"
```

The project depends on `foamlib[preprocessing,postprocessing]`. Read-only
operations work without a loaded OpenFOAM environment; running native tools
requires their commands on `PATH`.

Optional manual page:

```bash
./scripts/install_manpage.sh
man ofti
```

## Quick start

```bash
# Interactive case browser (real terminal only)
ofti CASE

# Scriptable diagnostics
ofti --plain knife preflight CASE --json
ofti knife status CASE --table

# Start, inspect, and stop a tracked solver
ofti watch start CASE --background
ofti watch jobs CASE --table
ofti watch stop CASE --signal TERM

# Prove and move a minimal runnable case
ofti bundle case CASE --output case.ofti.tar.gz --smoke --json
ofti bundle extract case.ofti.tar.gz --to CASE_COPY --run --background --json
```

Run `ofti -h` and `ofti <group> -h` for the authoritative option list.

## Commands

The installed entry point supports these top-level commands:

| Command | Purpose |
| --- | --- |
| `ofti knife ...` | Inspect, validate, compare, edit, adopt, and report. |
| `ofti plot ...` | Summarize solver-log metrics and residuals. |
| `ofti watch ...` | Inspect logs and control tracked jobs. |
| `ofti run ...` | Run solvers/tools, queues, smoke tests, resize, and studies. |
| `ofti bundle ...` | Create or extract runnable case/campaign archives. |
| `ofti result ...` | Create or extract verified result/restart archives. |
| `ofti plugins ...` | List installed plugin surfaces and diagnose load failures. |
| `ofti version` | Print the package version. |

Useful workflows:

```bash
# Reduce a field or extract a stable scalar from sampled output
ofti knife metric CASE --field p --time latest --reduction mean --json
ofti knife metric CASE postProcessing/probes/0/p \
  --name stagnation-p --value-column 1 --json

# Safely change MPI size at a complete checkpoint
ofti knife checkpoint CASE --common --np auto --json
ofti run restart-plan CASE --from 8 --to 16 --json
ofti run resize-parallel CASE --from 8 --to 16 --json

# Queue cases and record outcomes
ofti run queue CASE_A CASE_B --max-parallel 1 --json

# Generate a dictionary-aware sweep and package it for another host
ofti run parametric CASE \
  --grid-axis application=simpleFoam,pisoFoam \
  --output-root runs/study \
  --bundle-set study.ofti-set.tar.gz

# Preserve completed output separately from a runnable bundle
ofti result pack CASE --output results.ofti.tar.gz --json
```

Detailed examples and behavior are in [docs/cli.md](docs/cli.md).

## CLI contract

- `--plain` / `--no-tty` guarantees non-interactive execution. A bare case path
  without a terminal exits 2 with a concise diagnostic.
- `--json` is the automation surface. Every object carries `schema_version` and
  `command`; select the stable v2 envelope with `--json-version 2`.
- `--table` requests aligned human output where supported.
- `--json` and `--table` are mutually exclusive.
- stdout carries primary output and stderr carries usage diagnostics.
- Exit codes are `0` success, `1` operational/check failure, and `2` invalid
  input.
- Large-log workflows use bounded reads by default; `--easy-on-cpu` further
  reduces polling and tail sizes.

Persisted JSON uses `format` and `format_version`. Configuration precedence,
runtime records, archive layouts, schemas, and examples are documented in
[docs/runtime-files.md](docs/runtime-files.md) and
[docs/formats.md](docs/formats.md).

## Curses interface

`ofti CASE` opens the TUI only when stdin and stdout are terminals. Its Overview
combines case status, live/tracked processes, criteria, ETA, log metrics, and
residual summaries. Menus expose dictionary browsing/editing, boundary and
initial-condition views, mesh/run/post-processing actions, cleanup, and config.
Unavailable OpenFOAM actions are disabled with a reason.

See [docs/tui.md](docs/tui.md) for keys and supported behavior.

## Plugins

Solver-family assumptions belong in optional plugins, not generic core.
`plugins/ofti-hy2foam` provides stock hy2Foam field presets, physical/charge
diagnostics, preflight checks, and comparison helpers.
`plugins/hy2foam-mod` adds only modified/NN-fork behavior.

Plugins declare framework-neutral `CommandSpec` objects and use the same JSON
output contract as core commands. Inspect discovery with `ofti plugins list`
and `ofti plugins doctor`. See the
[hy2Foam plugin README](plugins/ofti-hy2foam/README.md).

## Architecture and development

```text
foamlib adapter + OFTI library -> CLI adapter
                            \-> TUI adapter
```

- `ofti/foamlib` is the only direct upstream `foamlib` integration layer.
- `ofti/core`, `ofti/foam`, and `ofti/tools` own reusable behavior.
- `ofti/app/cli_adapters` and the curses modules are thin interfaces.

The full boundary contract is in [docs/layering.md](docs/layering.md).

Run the mandatory gate:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Real OpenFOAM tests are explicit opt-in checks; see
[docs/testing.md](docs/testing.md) and
[docs/real_case_coverage.md](docs/real_case_coverage.md).

## Documentation

Start at [docs/README.md](docs/README.md). The committed manual source is
[man/ofti.1.scd](man/ofti.1.scd), and release steps are in
[docs/releasing.md](docs/releasing.md).

## License

GPL-3.0-or-later.
