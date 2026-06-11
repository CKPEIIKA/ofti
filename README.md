# DISCLAIMER

THIS IS VIBE-CODED SOFTWARE. EXPECT ROUGH EDGES.

# OFTI(1)

```
  ____  ______ _______ _____
 / __ \\ |  ___|__   __|_   _|
| |  | | |__     | |    | |
| |  | |  __|    | |    | |
| |__| | |       | |   _| |_
 \\____/|_|      |_|  |_____|
```

## NAME

ofti – OpenFOAM Terminal Interface (TUI)

## SYNOPSIS

```
python -m ofti.app.cli /path/to/case
ofti /path/to/case
```

Install from the repo root:

```bash
# uv (recommended)
uv tool install .
# or for local project venv:
uv venv
uv pip install -e .

# pip
python -m pip install .
# or editable for development:
python -m pip install -e .

# pipx (isolated app install)
pipx install .
```

`ofti` now depends on `foamlib[preprocessing,postprocessing]` by default.
If your environment is missing these extras, related features stay disabled in TUI with hints.

## DESCRIPTION

`ofti` is a small curses-based interface for OpenFOAM cases. It focuses on
fast browsing/editing of dictionaries, a boundary/initial-conditions view,
and common tools (mesh, run, post-process, diagnostics).

If the provided path is not an OpenFOAM case, `ofti` opens a folder picker
to select a valid case directory.
On startup, the TUI first shows a case chooser with currently visible running
solver cases, the current case when applicable, and a "Choose from a directory"
entry that opens the folder picker.
After a case is selected, the TUI opens the fast `OFTI menu`. The menu uses
cheap case metadata by default so startup stays responsive over SSH and small
terminals get a compact two-line header instead of a tall banner. The first
menu is workflow-oriented: `Captains Deck`, `Prepare`, `Mesh`, `Physics`,
`Numerics`, `Launch`, `Flight`, `Analyze`, and `Case Ops`. Open `Captains Deck`
from the menu to enter the heavier read-only control deck on demand. Wide
terminals show a right-side inspector for the currently selected menu item;
narrow terminals keep the compact list-first layout.
The captains deck consolidates safe CLI diagnostics such as case status, live jobs/
processes, runtime criteria, ETA, log metrics, residual summaries, alert cards,
Case DNA, mission-scope sparklines, a folded log signal view, Resource Watch,
setup fingerprinting, Case Lint findings, and a Mesh Radar summary from
checkMesh data when available. Inside the captains deck, use Tab/`l` and `h` to move
between panels and Enter to open the selected panel details.
Resource Watch flags risky write settings such as frequent writes without
`purgeWrite`; Mesh Radar surfaces common checkMesh quality risks with read-only
advice.
`ofti knife lint` exposes the first Case Doctor Pro checks as scriptable
read-only diagnostics with evidence and advice.
The `Numerics`, `Launch`, and `Flight` workflow entries now expose first-pass
decks: fvSchemes/fvSolution/controlDict summary, a go/no-go launch checklist,
and live solver/job/criteria action hints. `Change queue` includes a bounded
VCS diff preview for `system/`, `constant/`, and initial-condition files.

Menu/captains deck interface sketch (example):

```text
*------------------------------*- ofti -*-------------------------------*
| Case: reactiveShockTube             | Solver: hy2Foam                 |
| Status: ran                         | Latest time: 0.0002             |
| Mesh: 7200 cells, faces=30006, ...  | Parallel: 10; (scotch;)         |
| Faces: 30006 Points: 16814          | Disk: 34.0MB                    |
| Env: v1706                          | Keys: ? help / search : cmd     |
| Path: /path/to/openfoam/case        | Log: log.hy2Foam                |
*------------------------------------------------------------------------*

OFTI menu

>> Captains Deck
   Prepare
   Mesh
   Physics
   Numerics
   Launch
   Flight
   Analyze
   Case Ops
   Quit

Captains Deck opens the read-only control deck:

== OFTI CAPTAINS DECK // case=reactiveShockTube ======================
+- Flight --------------------------------------------------------------+
| solver simpleFoam  running yes  latest_time 0.5  jobs_running 1      |
+-----------------------------------------------------------------------+
+- Mission scopes -------------------+ +- Alerts -----------------------+
| Courant max  0.82  ####           | | WARN U residual above target   |
+------------------------------------+ +--------------------------------+

[normal mode: OpenFOAM env loaded | j/k move | Enter open | q quit]
```

## NON-INTERACTIVE CLI

`ofti` also provides non-TUI commands:

```bash
ofti knife ...
ofti plot ...
ofti watch ...
ofti run ...
```

Use built-in help at each level:

```bash
ofti -h
ofti -V
ofti knife -h
ofti watch log -h
ofti run tool -h
```

Most read-only diagnostic commands support `--json` for machine-readable output
and `--table` for aligned terminal tables. The TUI captains deck and related read-only
screens use the same service/table rendering as the CLI instead of raw key/value
dumps.
Use `ofti watch cases --table` for a read-only live case grid over a case set,
or add `--follow` to refresh it until interrupted. Add `--group-state` to make
the queue easier to scan and `--sort case|state|latest|eta|jobs` to choose the
row order.
For streaming tails (`watch log --follow` / `watch attach`), JSON is only for
non-follow mode.
Use `--easy-on-cpu` when you want bounded log reads and slower polling to keep
watch/status commands lighter on busy systems. The hidden legacy alias
`--lightweight` still works for compatibility.

Examples:

```bash
ofti knife preflight CASE --json
ofti knife lint CASE --table
ofti knife changes CASE --table
ofti knife status CASE --table
ofti knife captains-deck CASE --table
ofti knife dna CASE --json
ofti knife monitors CASE --diff --table
ofti knife monitors CASE --write --monitor residuals --monitor courant --table
ofti knife resource CASE --table
ofti knife mesh-radar CASE --table
ofti knife current --root REPO --recursive --live --table
ofti plot metrics CASE --table
ofti watch jobs CASE --table
ofti watch cases --set STUDY --glob 'case_*' --table
ofti watch cases --set STUDY --glob 'case_*' --group-state --sort eta --table
ofti knife initials CASE --json
ofti knife copy CASE_COPY --case CASE
ofti knife current --root REPO --recursive --live --json
ofti knife adopt --root REPO --all-untracked --json
ofti knife manifest write CASE --record-inputs-copy --json
ofti knife manifest verify runs/.../receipt.json --json
ofti knife manifest restore runs/.../receipt.json --to RESTORED_CASE --json
ofti watch jobs CASE --json
ofti watch pause CASE --all
ofti watch resume CASE --all
ofti watch stop CASE --signal TERM
ofti watch log CASE --lines 80 --json
ofti watch log CASE --follow --easy-on-cpu
ofti run tool --list --case CASE --json
ofti run solver CASE --dry-run --json
ofti run solver CASE --write-manifest --json
ofti run solver CASE --write-manifest --record-inputs-copy --json
ofti run solver CASE --parallel 8 --clean-processors --json
ofti run solver CASE --parallel 8 --no-prepare-parallel --json
ofti run resize-parallel CASE --from 8 --to 16 --table
ofti run resize-parallel CASE --to 16 --dry-run --table
ofti run matrix CASE --param application=simpleFoam,pisoFoam --no-launch --json
ofti run parametric CASE --entry application --values simpleFoam,pisoFoam --json
ofti run parametric CASE --csv studies/parametric.csv --run-solver --max-parallel 4 --json
ofti run parametric CASE --grid-axis application=simpleFoam,pisoFoam --grid-axis transport:nu=1e-5,2e-5 --json
ofti run status --set CASE_SET --fast --easy-on-cpu --json
```

### Knife Workflows

Campaign-wide live status from repo root:

```bash
ofti knife current --root . --recursive --live --json
```

- `jobs_tracked_running`: tracked jobs from OFTI registry only.
- `jobs_running`: tracked + live untracked solver processes.
- `jobs_total`: tracked jobs + currently discovered untracked running processes.
- `runs`: canonical run view that collapses a launcher/wrapper and solver ranks
  into one row where OFTI can identify the process group.

Bulk-adopt externally launched runs under repo root:

```bash
ofti knife adopt --root . --all-untracked --json
```

Equivalent explicit form:

```bash
ofti knife adopt --root . --recursive --json
```

Safe parallel launcher defaults (can be disabled explicitly):

```bash
ofti knife run CASE --parallel 2 --sync-subdomains --prepare-parallel --json
```

- `--sync-subdomains` updates `system/decomposeParDict:numberOfSubdomains`.
- `--prepare-parallel` runs parallel prelaunch (`decomposePar -force`, optional cleanup).
- Optional opt-out flags: `--no-sync-subdomains`, `--no-prepare-parallel`.

Safe parallel resize/resume flow:

```bash
ofti run resize-parallel CASE --from 8 --to 16 --dry-run --table
ofti run resize-parallel CASE --from 8 --to 16 --table
```

The resize workflow writes a case snapshot, requests `stopAt writeNow`, waits for
solver stop, reconstructs the latest decomposed time, removes old `processor*`
directories, updates `numberOfSubdomains`, sets `startFrom latestTime`, runs
`decomposePar -force -latestTime`, and restarts the solver with the new rank
count unless `--no-start` is used.

Adopted runs are normalized into the same run registry used by `watch jobs`,
`knife current`, and `knife status`. When procfs access is limited, OFTI reports
that live process discovery may be incomplete instead of silently treating the
registry as empty.

Runtime criteria now respect explicit runTimeControl gate messages in logs:

- `Conditions not met` prevents premature auto-pass from numeric-only checks.
- Criteria stay `unknown`/unmet until gate lines report conditions are met.
- Unknown criteria include a reason such as not enough samples, no matching log
  samples, startup window, or unavailable trend.

For very large logs, analysis/tail paths use bounded recent log windows to stay
responsive, and the TUI log viewer falls back to a bounded tail view for very
large files.

Run manifests for reproducible runs:

```bash
ofti run solver CASE --write-manifest --json
ofti run solver CASE --write-manifest --record-inputs-copy --json
ofti knife manifest write CASE --record-inputs-copy --json
ofti knife manifest verify runs/.../receipt.json --json
ofti knife manifest restore runs/.../receipt.json --to RESTORED_CASE --json
ofti knife manifest restore runs/.../receipt.json --to CASE_COPY --only system,constant --json
```

- `--write-manifest` writes an immutable manifest JSON under `./runs/` in the
  directory where you launch the command.
- Hash-only receipts are verification-grade: they let you detect drift.
- `--record-inputs-copy` upgrades the receipt to restore-grade by copying
  `system/`, `constant/`, and `0/` next to the receipt.
- Receipts now also record build/runtime provenance:
  solver binary hash, linked-library hash set, compiler flags, and selected
  OpenFOAM environment variables.
- `--receipt-file` overrides the destination explicitly; relative paths resolve
  from the current working directory.
- `--write-receipt` and `--receipt-file` remain as legacy aliases for existing
  scripts; new commands should prefer `--write-manifest` and `--manifest-file`.
- `knife manifest verify` checks the current case against recorded hashes.
- `knife manifest verify` also checks solver binary and linked-library drift.
- `knife manifest restore` recreates inputs only when the receipt includes the
  recorded input copy.
- `knife manifest restore --only/--skip` lets you restore only selected roots
  from `system`, `constant`, and `0`.
- `knife receipt ...` remains as a legacy alias for existing scripts.

External watcher integration (for example `scripts/oftools/ofwatch`) is
expected to run through tool presets in `ofti.tools` and can be executed with
`ofti run tool <name> --case CASE`.

For command-level details, prefer built-in help such as `ofti knife -h`,
`ofti watch -h`, and `ofti run -h`.

## UNIX CLI CONTRACT

- `-h/--help` is available at each command level.
- `-V/--version`, `--version`, and `ofti version` print the package version.
- `--json` is optional machine output for automation.
- `--table` is optional aligned human output for structured read-only commands.
- `--json` and `--table` are mutually exclusive.
- Command output goes to `stdout`; parse/usage errors go to `stderr`.
- Exit codes:
  - `0` success
  - `1` operational failure/check failed
  - `2` invalid input/usage validation failure

## REQUIREMENTS

- Python 3.10+
- `foamlib[preprocessing,postprocessing]` (dictionary IO, parametric generation, table loading)
- OpenFOAM environment on `PATH` for running tools (optional for read-only)

## DEVELOPMENT QUALITY

Current repo checks:

- `ruff check`
- `ty check`
- `pytest` with coverage gate `--cov-fail-under=85`

Opt-in real OpenFOAM tests are available for critical run-control paths across
canonical tutorial profiles. They clone real tutorial cases with PyFoam, run
`blockMesh`/`checkMesh`, exercise read-only decks/lint/resource/mesh services,
discover and adopt an untracked live solver, start a tracked solver, mutate
`controlDict` while it is running, verify the change queue diff,
pause/resume/stop it, write monitor include files, generate a report artifact,
and attempt short parallel restarts/reconstructed mesh checks when MPI is
available. The default opt-in profile set is `icoFoam-cavity`,
`simpleFoam-pitzDaily`, and `interFoam-damBreak`:

```bash
OFTI_ENABLE_REAL_CASE_TESTS=1 \
pytest -o addopts='' tests/test_real_openfoam_toy_case.py
```

Limit or expand the profile matrix with `OFTI_REAL_CASES`:

```bash
OFTI_ENABLE_REAL_CASE_TESTS=1 OFTI_REAL_CASES=icoFoam-cavity \
pytest -o addopts='' tests/test_real_openfoam_toy_case.py

OFTI_ENABLE_REAL_CASE_TESTS=1 OFTI_REAL_CASES=all \
pytest -o addopts='' tests/test_real_openfoam_toy_case.py
```

These tests are skipped by default because they launch real OpenFOAM/PyFoam
processes and mutate a temporary cloned case. They require `pyFoamCloneCase.py`,
`blockMesh`, `checkMesh`, `decomposePar`, `reconstructParMesh`, `git`, and the
tutorial solver on `PATH`; MPI is optional and only gates the parallel-restart
scenarios.

Adapter layout:

- `ofti/app/cli.py`: top-level `ofti` entrypoint; delegates non-interactive
  groups to the CLI tools dispatcher and opens the TUI otherwise.
- `ofti/app/cli_tools.py`: compatibility dispatcher for legacy imports.
- `ofti/app/cli_adapters/`: argparse, output formatting, and exit-code mapping
  by command group (`knife`, `plot`, `watch`, `run`).
- `ofti/tools/` and `ofti/core/`: shared services and domain logic used by both
  CLI and TUI.
- `ofti/foamlib/`: the only direct upstream `foamlib` integration layer.

## MODES

- **Normal**: OpenFOAM environment detected; tools available.
- **Limited**: OpenFOAM env not detected; tools are disabled, editor remains usable.

## KEYS (GLOBAL)

- `j/k` or arrows: move
- `Enter`: select
- `h` or `Esc`: back
- `q`: quit (root menu only)
- `/`: menu search with `fzf` (if installed)
- `s`: global dictionary search
- `:`: command line
- `!`: shell/terminal
- `?`: help for current menu/tool

## EDITOR

- Browse `system/`, `constant/`, and `0*` files
- Entry preview shows type, value, comments, and boundary info
- Values are validated (dimensions, fields, vectors, etc.)
- `e`/`Enter` to edit; `v` to view file; `o` to open `$EDITOR`

## STAGES AND COMMAND MODE

Common actions are grouped under workflow tabs: Captains Deck, Prepare, Mesh,
Physics, Numerics, Launch, Flight, Analyze, and Case Ops. Numerics, Launch,
and Flight now open first-pass shared-service decks; deeper edit/run actions
still route through existing config/simulation services. Actions are disabled
with a clear reason when required files/environment are missing.

Command mode shortcuts:
- `:tool <name>` or `:<name>` runs tool aliases/presets.
- `:run ...`, `:knife ...`, `:watch ...`, `:plot ...` call non-interactive CLI.

Post‑Processing notes:
- `View logs` contains file view, live tail, and log analysis summary.
- `PostProcessing tables` loads table-like outputs using foamlib postprocessing extras.
- `Sampling & sets` includes `postProcess`-driven sampling actions.
- `Parametric wizard` supports single-entry, CSV, and grid studies (when preprocessing extras are installed).

## PARAMETRIC STUDIES

CLI and TUI now share the same foamlib-backed generation paths:

```bash
# single-entry sweep
ofti run parametric CASE --dict system/controlDict --entry application --values simpleFoam,pisoFoam

# CSV study
ofti run parametric CASE --csv studies/parametric.csv

# grid study
ofti run parametric CASE \
  --grid-axis application=simpleFoam,pisoFoam \
  --grid-axis constant/transportProperties:nu=1e-5,2e-5
```

Minimal CSV schema example (`studies/parametric.csv`):

```csv
application,transportModel,nu
simpleFoam,Newtonian,1e-05
pisoFoam,Newtonian,2e-05
```

Use `--run-solver` with `--max-parallel` to immediately queue generated cases.

## RUN QUEUES

`ofti run queue` is the CLI-first queue primitive. By default it runs cases
sequentially (`--max-parallel 1`), records each solver log, waits for a case to
finish or crash, classifies the outcome, and immediately advances to the next
case:

```bash
ofti run queue case_a case_b --json
ofti run queue --set CASE_SET --glob 'case_*' --max-parallel 1
```

Queue result rows include `returncode`, `state`, `outcome`, `stop_reason`,
`latest_time`, and `end_time`. Outcomes distinguish normal end-time completion,
criterion completion when detectable, crashes, and unknown stopped cases. Use
bounded parallel queueing only when the per-case final return code is less
important than throughput:

```bash
ofti run queue --set CASE_SET --glob 'case_*' --max-parallel 6 --backend foamlib-async
```

## FILES

- Case root with `system/controlDict`
- Optional presets: `ofti.parametric`
- Logs: `log.*`
- Config: `~/.config/ofti/config.toml` (or `$OFTI_CONFIG`)

## LICENSE

GPL-3.0-or-later.

 
