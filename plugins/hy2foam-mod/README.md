# ofti-hy2foam-mod

Modified / NN-fork hy2Foam plugin for [OFTI](../../README.md). It layers over
`ofti-hy2foam` and owns fork-specific checks such as `NNcompiled`,
`precompiledModel`, `stateInputOrder`, `inputOrder`, and `outputOrder`.

Keep stock hy2Foam diagnostics in `plugins/ofti-hy2foam`; this package is only
for modified solver branches and model-runtime inspection.

## Install

```bash
pip install ./plugins/ofti-hy2foam
pip install ./plugins/hy2foam-mod
```

The plugin registers through the `ofti.plugins` entry point. Once installed, its
commands appear under `ofti knife` automatically.

## Commands

```bash
# Fork-specific preflight for NNcompiled/model-order contracts
ofti knife hy2foam-mod-preflight CASE --json
```

## Bundle hints

When `ofti bundle` sees NNcompiled/model-order markers, this plugin adds
manifest warnings for the target host: the destination must have the same
modified hy2Foam runtime and compatible model/order assets. The archive logic
stays in OFTI core; the plugin only contributes domain-specific warnings.

## Tests

```bash
uv run pytest plugins/hy2foam-mod/tests
```
