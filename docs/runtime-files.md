# OFTI TOML, Preset, and JSON Files


OFTI keeps user-facing files small and inspectable. JSON files are durable
machine records; TOML is only used for user configuration.

The stable format/versioning policy, examples, and JSON Schema files are
documented in `docs/formats.md`, `docs/examples/formats/`, and `docs/schemas/`.

### User config TOML

Config path: `~/.config/ofti/config.toml`, or `$OFTI_CONFIG` when set.

```toml
fzf = "auto"                  # auto | on | off
use_runfunctions = true       # prefer OpenFOAM RunFunctions helpers when present
use_cleanfunctions = true     # prefer OpenFOAM CleanFunctions helpers when present
enable_entry_cache = true
enable_background_checks = true
enable_background_entry_crawl = false
validate_on_save = false
openfoam_bashrc = "/opt/openfoam/etc/bashrc"
courant_limit = 1.0
example_paths = ["~/OpenFOAM", "/data/openfoam-cases"]

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

[colors]
focus_fg = "black"
focus_bg = "cyan"

[keys]
up = ["k"]
down = ["j"]
select = ["l", "\n"]
back = ["h", "ESC"]
quit = ["q"]
help = ["?"]
command = [":"]
search = ["/"]
global_search = ["s"]
top = ["g"]
bottom = ["G"]
view = ["v"]
```

Environment overrides include `OFTI_FZF`, `OFTI_USE_RUNFUNCTIONS`,
`OFTI_USE_CLEANFUNCTIONS`, `OFTI_ENABLE_ENTRY_CACHE`,
`OFTI_ENABLE_BACKGROUND_CHECKS`, `OFTI_ENABLE_BACKGROUND_ENTRY_CRAWL`,
`OFTI_BASHRC`, `OFTI_COURANT_LIMIT`, `OFTI_EXAMPLE_PATHS`,
`OFTI_CASE_ROOT`, `OFTI_QUEUE_ROOT`, `OFTI_BUNDLE_OUTPUT_DIR`,
`OFTI_SMOKE_ROOT`, `OFTI_MANIFEST_ROOT`, `OFTI_SNAPSHOT_ROOT`,
`OFTI_TMP_ROOT`, `OFTI_DEFAULT_PARALLEL`, `OFTI_RUN_POLL_INTERVAL`,
`OFTI_LOG_TAIL_BYTES`, `OFTI_QUEUE_MAX_PARALLEL`,
`OFTI_QUEUE_POLL_INTERVAL`, `OFTI_QUEUE_BACKEND`, `OFTI_BUNDLE_MESH`,
`OFTI_BUNDLE_TIME`, `OFTI_BUNDLE_SMOKE_ITERATIONS`,
`OFTI_BUNDLE_SMOKE_TIMEOUT`, `OFTI_WATCH_POLL_INTERVAL`, and
`OFTI_WATCH_TAIL_BYTES`.

### Case-local preset files

These files live in the case root and are intentionally line-oriented, not TOML:

- `ofti.tools`: extra tool presets for `ofti run tool` and TUI tool menus.
- `ofti.postprocessing`: extra post-processing presets, shown with `[post]`.
- `ofti.parametric`: parametric study presets.

Tool preset syntax:

```text
name: shell-like command with args
check mesh strict: checkMesh -allGeometry -allTopology
latest reconstruct: reconstructPar -latestTime
```

Parametric preset syntax accepts either pipe or compact colon form:

```text
solver sweep | system/controlDict | application | simpleFoam,pisoFoam
nu sweep: constant/transportProperties nu 1e-05,2e-05
```

### Runtime JSON records

- `.ofti/jobs.json`: `ofti.jobs` v1 tracked solver/tool/watcher registry for
  `watch jobs`, stop, pause/resume, attach, and adopt workflows. OFTI still
  reads the legacy raw-list layout.
- `.ofti/runs/*.json` and `.ofti/current_run.json`: normalized run identities;
  OFTI uses them to collapse launcher/wrapper/rank processes into one run view.
- `.ofti/watch.json`: persisted watch output profile and external watcher state.
- `.ofti/tool_catalog.json`: optional exported tool catalog from
  `ofti run tool --list` helpers.
- `.ofti/case_snapshot.json`: setup snapshot for reports and safety checks.
- `.ofti/parallel-resize/*/case_snapshot.json` and `snapshot.json`: setup
  snapshot plus stable `ofti.snapshot` manifest created before resize/restart
  operations.
- `.ofti/queues/queue-*.json`: `ofti.queue-record` v1 durable queue
  plan/progress record with started, finished, failed-to-start, outcome, and
  stop reason rows.
- `.ofti/queues/queue-*.events.jsonl`: append-only queue event journal; use
  `ofti run queue-summary PATH` to rebuild counters from the journal.
- `.ofti/smoke/*/summary.json` or `--out DIR/summary.json`: bounded smoke-test
  result with command, normalized controls, log path, times seen, and optional
  physical-check payload.
- `runs/*/manifest.json` or `--manifest-file PATH`: `ofti.run-manifest` v1
  reproducibility manifest containing launch settings, OpenFOAM/build
  provenance, selected setup hashes, and optional copied inputs under `inputs/`.

Legacy receipt names are accepted for compatibility, but new output and docs use
`manifest`.
