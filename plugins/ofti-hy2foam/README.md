# ofti-hy2foam

hy2Foam (hyStrath) diagnostics plugin for [OFTI](../../README.md). It adds
solver-family field presets, a physical-rule profile, and extra `knife` commands
without putting any hy2Foam-specific assumptions into OFTI core. This plugin
targets **stock/original hy2Foam**; the modified/NN fork lives in a separate
`hy2foam-mod` plugin.

## Install

```bash
pip install ./plugins/ofti-hy2foam
```

The plugin registers through the `ofti.plugins` entry point, so once installed
its presets, profile, and commands appear under `ofti knife` automatically.

## Field presets

Use with `ofti knife compare-fields --preset <name>` or
`ofti knife physical --fields ...`:

| Preset            | Fields |
| ----------------- | ------ |
| `air5`            | `N2 O2 NO N O Tt Tv p rho` |
| `air11`           | 11-species air set (+ `p`, `rho`) |
| `hy2foam-transport` | `Dmix_* rhoD_* J_* sumJ qDiff` |
| `hy2foam-2T`      | `Tt Tv Tov e ev` |
| `hy2foam-wall`    | `wallHeatFlux qCond qDiff p` |

## Physical profile

```bash
# Append hy2Foam fields/rules to a physical scan and emit the plugin diagnostics
# (species sum, two-temperature sanity) under a `diagnostics` key:
ofti knife physical CASE --profile hy2foam --json
```

## Commands

Every command supports `--json` (machine output stamped with `schema_version`
and `command`) and returns `0` on success, `1` on a failed check.
`hy2foam-preflight` and `hy2foam-compare-check` also accept `--table` for aligned
human output (mutually exclusive with `--json`).

```bash
# Charge / ionization observability (electron + ion number density, net imbalance)
ofti knife charge CASE --time latest --json

# Stock hy2Foam preflight (OpenFOAM version, hyStrath libs, required fields,
# species/patch + species-order consistency, turbulence, duplicate functions)
ofti knife hy2foam-preflight CASE --json

# Check a case pair before a cellwise compare (latest common time + same mesh)
ofti knife hy2foam-compare-check LEFT_CASE RIGHT_CASE --json

# Compare patch field values between two same-mesh cases
ofti knife hy2foam-patch-compare LEFT_CASE RIGHT_CASE \
    --patch wall --preset hy2foam-wall --json
```

> Charge diagnostics are observational only — charged species do not imply
> ambipolar diffusion is configured.

## Tests

```bash
uv run pytest plugins/ofti-hy2foam/tests
```
