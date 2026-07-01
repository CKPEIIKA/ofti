# OFTI File and JSON Formats

OFTI keeps OpenFOAM cases native. A bundle is still a case tree with `system/`,
`constant/`, time directories, and one OFTI manifest under `.ofti/`; runtime
state is kept in `.ofti/` beside the case.

## Versioning Rules

Persisted JSON files use the same top-level contract:

```json
{
  "format": "ofti.<name>",
  "format_version": 1
}
```

Existing v1 files may also carry compatibility aliases such as `schema_version`,
`version`, or `manifest_kind`; new readers accept those aliases, but new docs and
examples use `format` plus `format_version` for persisted state.

CLI JSON is a separate contract because it is command output, not stored state:

```json
{
  "schema_version": 1,
  "command": "bundle",
  "ok": true
}
```

Command-specific keys remain top-level in schema v1 for backwards compatibility.
Scripts should require `--json` and should not parse table output.

## Common Rules

- Timestamps in new persisted formats are UTC RFC3339 strings like
  `2026-06-29T22:54:18Z`.
- Portable formats use relative POSIX paths.
- Local runtime state may use absolute paths and records `case_dir` when useful.
- Unknown extension data should live under an `extensions` object keyed by a
  reverse-DNS or package namespace, for example `ofti.hy2foam`.
- Writers should be strict. Readers may accept compatible v1 aliases and legacy
  layouts.
- Breaking changes require a new major `format_version` and a migration note.

## User Config: `ofti.toml`

Case-local/user TOML is human-edited configuration, not runtime state.
Recommended header:

```toml
format = "ofti.config"
format_version = 1

# Global defaults only. Keep case-specific solver/physics in OpenFOAM files.

[paths]
case_root = "~/OpenFOAM"
queue_root = "~/.local/state/ofti/queues"
bundle_output_dir = "~/ofti-bundles"
smoke_root = "~/.cache/ofti/smoke"
manifest_root = "~/.local/state/ofti/manifests"
snapshot_root = "~/.local/state/ofti/snapshots"
tmp_root = "~/.cache/ofti/tmp"

[run]
default_parallel = 0
poll_interval = 0.25
log_tail_bytes = 262144

[queue]
backend = "process"
max_parallel = 1
poll_interval = 0.25
root = "~/.local/state/ofti/queues"

[bundle]
mesh = "auto"
time = "0"
smoke_iterations = 5
smoke_timeout = "60s"
output_dir = "~/ofti-bundles"

[watch]
poll_interval = 0.25
tail_bytes = 262144
```

Precedence is: CLI flags, environment variables, case-local `ofti.toml`, user
config, built-in defaults.

## Bundle Archive

A bundle archive is a portable case tree plus `.ofti/bundle.json`. The manifest
is authoritative; archive filenames are only hints.

Baseline archive format is `.tar.gz`. `.tar.zst` is optional when the `zstandard`
package is available. Writers sort paths and normalize tar metadata for stable
archives. Readers reject unsafe paths: absolute paths, `..`, and unsafe symlink
or link targets must not escape the destination.

Current bundle manifest: `ofti.case-bundle` v1.

## Run Manifest

Run manifests are provenance records for a launch or adopted run. Current format:
`ofti.run-manifest` v1, with compatibility `manifest_kind = ofti_run_manifest`.
They include case identity, launch settings, OpenFOAM/build provenance, input
hashes, and optional copied inputs for restore.

## Job Registry

`.ofti/jobs.json` is local runtime state for watched/adopted jobs. Current
format: `ofti.jobs` v1.

The registry is an object wrapper, not a raw list, so version, case, and update
metadata can evolve. Readers still accept the legacy raw-list layout. Writers use
an atomic write-then-rename path. Corrupt registry files are moved aside as
`jobs.json.corrupt.<timestamp>` before OFTI falls back to recoverable run
identity files.

## Queue Record

`.ofti/queues/queue-*.json` records a queue plan and progress summary. Current
format: `ofti.queue-record` v1. Rows include stable state/outcome/stop-reason
fields for automation. Each live queue also writes an append-only sibling
`queue-*.events.jsonl` journal with `created`, `started`, `finished`,
`failed_to_start`, and `completed` events so long campaign state can be audited
or rebuilt from events if the summary is interrupted.

## Snapshots

Snapshots under `.ofti/parallel-resize/` and other safety workflows write a
stable `ofti.snapshot` v1 manifest next to copied inputs. The directory layout
remains an implementation detail; external consumers should consume the
manifest.

## OpenFOAM Compatibility

Supported:

- native OpenFOAM case tree layout
- ASCII FoamFile dictionaries where parseable by foamlib or OFTI fallback logic
- scalar/vector/tensor-like internal fields where parseable
- uniform and nonuniform internalField forms
- decomposed `processor*` aggregation for selected workflows

Best effort:

- regex dictionary keys
- `#include` / `#includeIfPresent` references
- function-object outputs
- multi-region paths such as `constant/fluid/polyMesh`

Unsupported or rejected:

- evaluating `#codeStream`
- unknown binary field encodings
- path traversal in archives
- unsafe archive links or symlinks

## Schemas and Examples

Human examples live in `docs/examples/formats/`. Draft JSON Schemas for the main
machine-readable v1 formats live in `docs/schemas/`. The schemas document the
stable envelope; command-specific payloads may be stricter in service tests.
