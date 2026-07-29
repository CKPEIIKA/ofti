# CLI workflows

OFTI is CLI-first. The curses interface calls the same services, but automation
should use the installed `ofti` command and request `--json` where available.
Run `ofti -h` and `ofti <group> -h` for the authoritative option list.

## Contract

- `--plain` / `--no-tty` guarantees that curses is never entered.
- `--json` is the machine-readable surface. Schema v1 remains the default;
  select the stable v2 envelope with `--json-version 2` or
  `OFTI_JSON_VERSION=2`.
- `--table` requests aligned human output where supported.
- `--json` and `--table` are mutually exclusive.
- Primary output goes to stdout; usage diagnostics go to stderr.
- Exit `0` means success, `1` means an operational/check failure, and `2`
  means invalid input.

The top-level command groups are:

| Group | Purpose |
| --- | --- |
| `knife` | Inspect, validate, compare, edit, adopt, and report on cases. |
| `plot` | Summarize solver-log metrics and residuals. |
| `watch` | Inspect logs and control tracked jobs. |
| `run` | Run solvers/tools, queues, smoke tests, and parametric studies. |
| `bundle` | Pack or extract minimal runnable case archives and case sets. |
| `result` | Pack or extract completed output/restart state. |
| `plugins` | Inspect plugin entry points, versions, surfaces, and failures. |
| `version` | Print the authoritative package version. |

## Knife

Typical read-only diagnostics:

```bash
ofti knife preflight CASE --json
ofti knife doctor CASE --table
ofti knife status CASE --table
ofti knife criteria CASE --json
ofti knife eta CASE --json
ofti knife initials CASE --json
ofti knife physical CASE --time latest --fields p,U,rho,T --json
ofti knife physical CASE --field rho:min=0 --field T:min=0 --out checks
ofti knife compare-fields \
  --reference SERIAL_CASE --candidate PARALLEL_CASE --preset flow --out compare
```

`physical` reads supported ASCII and binary nonuniform internal fields and can
combine complete decomposed `processor*` fields. Unsupported binary layouts are
reported explicitly rather than guessed.

Use `metric` for direct field reductions, boundary-patch values, probe series,
or sampled-set scalar extraction:

```bash
ofti knife metric CASE --field p --time latest --reduction mean --json
ofti knife metric CASE --field wallHeatFlux --patch wall --reduction max --json

ofti knife metric CASE postProcessing/probes/0/p \
  --name stagnation-p --value-column 1 --json

ofti knife metric CASE 'postProcessing/sets/*/line_p.xy' \
  --name shock-x --threshold 0.3 --value-column 1 \
  --window 20 --max-span 1e-4 --json
```

Field mode reads uniform/nonuniform internal or patch values through OFTI's
normal field-I/O path and reports `min`, `max`, `mean`, finite counts, and the
selected reduction as `value`. Multi-component fields default to magnitude;
use `--component INDEX` for one component. Any nonfinite field value makes the
command exit `1`.

Plain-series mode reports the latest selected value. Threshold mode reports a
crossing coordinate from each matched profile. Both table modes include
`value`, `last_n_span`, sample counts, and `mature`; maturity remains `null`
unless an explicit `--max-span` is supplied.

Mutating commands make intent explicit:

```bash
ofti knife set CASE --edit system/controlDict:endTime=100 \
  --edit system/controlDict:writeInterval=10 --dry-run --json
ofti knife copy CASE_COPY --case CASE
ofti knife checkpoint CASE --common --np auto --json
ofti knife checkpoint CASE --quarantine-partial --json
ofti knife checkpoint CASE --quarantine-partial --apply --json
```

`knife set` only updates existing key paths by default and reports
`operation=update` with normalized before/after values. Use `--insert` to create
a missing key. Repeatable `--edit` uses one transaction: dry-run prints the
complete source-preserving diff, while apply stages and atomically replaces all
files after a snapshot. A failed replacement restores every touched file and
the transaction manifest records the rollback. `knife copy` never executes
case-provided scripts.

Campaign discovery and adoption:

```bash
ofti knife current --root REPO --recursive --live --table
ofti knife adopt --root REPO --all-untracked --json
ofti knife registry repair CASE --json
```

OFTI collapses recognizable launcher/wrapper/rank process groups into one run.
When process discovery is restricted, the payload reports that limitation
instead of silently claiming no jobs exist.

## Run

Start or inspect commands:

```bash
ofti run tool --list --case CASE --json
ofti run solver CASE --dry-run --json
ofti run solver CASE --parallel 8 --clean-processors --json
ofti run smoke CASE --iterations 20 --timeout 5m --out smoke --json
ofti run smoke CASE --parallel 4 --reconstruct --json
```

`run smoke --iterations N` works in a disposable copy, disables adaptive
stepping, and accepts a run only when all requested evidence agrees:

- exactly `N` logged steps reached the expected final time;
- the solver returned zero and wrote its clean `End` marker;
- the final time is nonzero and complete across the requested processor count;
- representative output fields can be read from every rank;
- when `--reconstruct` is requested, `reconstructPar` succeeds and the
  reconstructed fields are readable.

The JSON fields `failure_reasons`, `checkpoint`, `readable_fields`, and
`reconstruction` retain the evidence for failed smoke runs.

Inspect restart safety before changing MPI size:

```bash
ofti run restart-plan CASE --from 8 --to 16 --json
ofti run resize-parallel CASE --from 8 --to 16 --json
```

`restart-plan` is read-only. It reports the latest time common to every
processor, partial newer writes, actual/configured/expected MPI sizes, and the
ordered mutation plan. It exits nonzero when processor numbering, MPI size, or
checkpoint completeness is unsafe.

The service can request `writeNow`, stop the solver, snapshot inputs, select the
latest time complete across all processors, reconstruct it, remove obsolete
decomposition only after reconstruction is verified, update
`numberOfSubdomains`, redecompose, and optionally restart. Incomplete newer
times are quarantined before old decomposition is removed; they are never
treated as a valid resume point.

### Queues

The default queue is sequential and advances immediately after a case finishes
or fails:

```bash
ofti run queue CASE_A CASE_B --json
ofti run queue --set CASE_SET --glob 'case_*' --max-parallel 1
ofti run queue --set CASE_SET --glob 'case_*' \
  --max-parallel 6 --backend foamlib-async
```

Rows include return code, state, outcome, stop reason, latest time, and end
time. Queue records and their append-only event journals are documented in
[formats.md](formats.md).

### Parametric studies

Use dictionary-aware sweeps instead of clone-and-`sed` scripts:

```bash
ofti run parametric CASE \
  --grid-axis application=simpleFoam,pisoFoam \
  --grid-axis constant/transportProperties:nu=1e-5,2e-5 \
  --output-root runs/study

ofti run parametric CASE --csv studies/parametric.csv \
  --run-solver --max-parallel 4
```

Package a generated study for local-preparation/HPC handoff in the same
operation:

```bash
ofti run parametric CASE \
  --grid-axis 'constant/transportProperties:transportModel=Fick,Lewis' \
  --output-root runs/transport \
  --bundle-set transport-study.ofti-set.tar.gz
```

## Bundles

Single-case and campaign archives preserve ordinary OpenFOAM case trees:

```bash
ofti bundle case CASE --output case.ofti.tar.gz --mesh auto --time 0 --json
ofti bundle case CASE --output case.ofti.tar.gz --smoke --json
ofti bundle case CASE --output case.ofti.tar.gz \
  --run-manifest ~/ofti-runs/case/manifest.json --json
ofti bundle set CASE_A CASE_B --output study.ofti-set.tar.gz --json
ofti bundle set --cases-file cases.txt --cases-root . \
  --output study.ofti-set.tar.gz --json
ofti bundle extract case.ofti.tar.gz --to CASE_COPY --run --background --json
ofti bundle extract study.ofti-set.tar.gz --to STUDY --json
```

A case bundle contains the minimal runnable tree: `system/`, `constant/`, the
selected start time, local includes, optional case scripts/metadata, and a mesh
according to `--mesh`. Logs, `processor*`, `postProcessing`, and caches are
excluded by default. `--smoke` proves the extracted archive through the same
bounded solver service used by `run smoke`.

The deterministic archive embeds `.ofti/bundle.json` with relative paths,
hashes, solver and OpenFOAM hints, and warnings. A case-local run manifest and
build digest are carried when available and verified during extraction.
`--run-manifest PATH` overrides discovery and embeds an external manifest at
`.ofti/provenance/run-manifest.json` without modifying the source case.
Extraction rejects path traversal and unsafe links and uses staging before
publishing a bundle set.

`--cases-file` accepts one case path per line. Relative paths resolve from
`--cases-root`.

## Results

Result packs are deliberately separate from runnable bundles:

```bash
ofti result pack CASE --output results.ofti.tar.gz --json
ofti result pack CASE --output restart-state.tar.gz \
  --include-processors --json
ofti result unpack results.ofti.tar.gz --to RESULTS --json
```

They keep the selected reconstructed time, logs, post-processing output, and
case-local run manifests. `--include-processors` includes processor state only
when the selected time is complete across every processor.

## Watch and plot

```bash
ofti watch jobs CASE --table
ofti watch status CASE --json
ofti watch pause CASE --all
ofti watch resume CASE --all
ofti watch stop CASE --signal TERM
ofti watch log CASE --lines 80 --json
ofti watch log CASE --follow --easy-on-cpu
ofti plot metrics CASE --table
ofti plot residuals CASE --json
```

`watch status` keeps stable reason codes and also classifies the observed run
state as `STARTING`, `SOLVING`, `WRITING`, `STALLED_LOG`,
`PARTIAL_CHECKPOINT`, `MPI_FAILED`, or `FINISHED`. This classification is
evidence, not a hidden control action. Large-log reads are bounded by default.

## Plugins

Plugin discovery is inspectable rather than implicit:

```bash
ofti plugins list --json
ofti plugins doctor --json
```

`list` reports the entry-point name and source, installed distribution/version,
registered surfaces, and load errors. `doctor` exits 1 for load/registration
errors or for a loaded entry point that registered no OFTI surface.

Plugins may register framework-neutral `CommandSpec` providers under `knife`,
`run`, `watch`, and `result`, read-only progress metrics attached to status
payloads, field presets/profiles, and bundle hints. Plugin failures are reported
without making unrelated core commands unavailable.

## Run manifests

```bash
ofti run solver CASE --write-manifest --json
ofti run solver CASE --write-manifest --record-inputs-copy --json
ofti knife manifest write CASE --record-inputs-copy --json
ofti knife manifest verify CASE --json
ofti knife manifest restore MANIFEST --to RESTORED_CASE --json
```

The default case-local destination is
`CASE/runs/<timestamp>_<case>/manifest.json`. Configure a central root with
`[paths].manifest_root` or `OFTI_MANIFEST_ROOT`, or pass `--manifest-file`.
Hash-only manifests detect drift; `--record-inputs-copy` also carries restorable
`system/`, `constant/`, and `0/` inputs. Build provenance includes solver and
linked-library hashes plus selected OpenFOAM environment values.

Format contracts and examples live in [formats.md](formats.md). Runtime paths,
configuration precedence, and case-local preset files are in
[runtime-files.md](runtime-files.md).
