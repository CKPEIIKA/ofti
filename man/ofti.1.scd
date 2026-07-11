ofti(1) "OFTI 0.9.1" "User Commands"

# NAME

ofti - scriptable OpenFOAM case utilities and terminal interface

# SYNOPSIS

*ofti* [*-h*] [*--debug*] [*-V*] [_CASE_]

*ofti knife* _COMMAND_ [options]

*ofti run* _COMMAND_ [options]

*ofti watch* _COMMAND_ [options]

*ofti plot* _COMMAND_ [options]

*ofti bundle* _CASE_ *--output* _ARCHIVE_ [options]

*ofti unbundle* _ARCHIVE_ *--to* _CASE_ [options]

*ofti result* _COMMAND_ [options]

# DESCRIPTION

OFTI is a CLI-first convenience layer over foamlib and native OpenFOAM tools.
Without a non-interactive command it opens the curses interface for _CASE_, or
the current directory. The CLI and TUI call the same services.

Commands do not silently overwrite case data. Mutating operations expose an
explicit apply, output, snapshot, or destination option. Machine consumers
should request *--json* and check both the process exit status and the returned
*schema_version*.

# GLOBAL OPTIONS

*-h*, *--help*
	Show command help. Every command and subcommand provides its own help.

*--debug*
	Enable debug logging and verbose error reports.

*-V*, *--version*
	Print the OFTI version.

# COMMANDS

*knife*
	Inspect, validate, compare, edit, adopt, stop, and report on cases. Important
	subcommands include *doctor*, *preflight*, *checkpoint*, *physical*,
	*compare-fields*, *manifest*, *registry*, *status*, *current*, *adopt*,
	*set*, *criteria*, *eta*, *report*, and *campaign*.

*run*
	Run solvers and tools, smoke-test portable case copies, resize parallel runs,
	generate parameter matrices, and execute queues. Subcommands are *tool*,
	*solver*, *smoke*, *resize-parallel*, *matrix*, *parametric*, *queue*,
	*queue-summary*, and *status*.

*watch*
	Inspect logs and control tracked jobs. Subcommands are *jobs*, *status*,
	*log*, *attach*, *start*, *pause*, *resume*, *interval*, *output*, *run*,
	*stop*, and *external*.

*plot*
	Render terminal plots from solver logs and criteria data.

*bundle*, *unbundle*
	Create or extract a portable minimal case archive. A bundle retains native
	OpenFOAM layout and includes a checksummed *.ofti/bundle.json* manifest.
	Unbundle can optionally smoke-test or start the restored case.

*result*
	Pack and unpack result or restart state. Processor state is included only
	when the selected time is complete across every processor directory.

# OUTPUT AND EXIT STATUS

Human-readable output is concise. *--table* selects stable tabular output where
supported. *--json* emits a machine envelope with *schema_version*, *command*,
*ok*, warnings, errors, and command data. Diagnostics go to standard error.

*0*
	Success, or a report-only diagnostic completed.

*1*
	Operational failure, failed check when requested, or solver failure.

*2*
	Invalid arguments, unknown preset/profile, or usage validation failure.

# ENVIRONMENT

*OFTI_CONFIG*
	Path to the user TOML configuration.

*OFTI_JSON_VERSION*
	Default JSON envelope version. Version 1 remains the default in OFTI 0.9.1.

*OFTI_WATCH_STALE_AFTER_SECONDS*
	Age threshold for STALE_LOG and NO_PROGRESS evidence.

*OFTI_ENABLE_REAL_CASE_TESTS*
	Enable opt-in tests that launch real OpenFOAM commands.

*WM_PROJECT_DIR*, *WM_PROJECT_VERSION*, *FOAM_RUN*
	OpenFOAM environment hints used for tool and tutorial discovery.

# FILES

*_CASE_/ofti.toml*
	Case-local configuration. CLI flags and environment variables take priority.

*~/.config/ofti/config.toml*
	Default user configuration when *OFTI_CONFIG* is unset.

*_CASE_/.ofti/jobs.json*
	Atomic tracked-job registry. Repair it from durable run identities with
	*ofti knife registry repair CASE*.

*_CASE_/.ofti/runs/*.json*
	Durable run identity records used for process ownership recovery.

*_CASE_/runs/*
	Case-local immutable run manifests and optional input snapshots.

*_CASE_/.ofti/queues/*
	Queue summaries and append-only event journals.

# EXAMPLES

Inspect a case without starting the TUI:

```
ofti knife preflight CASE --json
ofti knife status CASE --table
```

Start, inspect, and safely stop a solver:

```
ofti watch start CASE --background
ofti watch jobs CASE --table
ofti watch stop CASE --signal TERM
```

Resize a stopped decomposed run after validating its checkpoint:

```
ofti knife checkpoint CASE --common --np auto --json
ofti run resize-parallel CASE --to 8 --json
```

Move a minimal case to another host:

```
ofti bundle CASE --output case.ofti.tar.gz --smoke --json
ofti unbundle case.ofti.tar.gz --to CASE_COPY --run --background --json
```

Run a sequential queue that continues after a failed case:

```
ofti run queue CASE_A CASE_B --max-parallel 1 --json
```

# DIAGNOSTICS

Use *ofti knife doctor CASE* for case-structure diagnostics and *ofti knife
preflight CASE* for launch prerequisites. *ofti watch status CASE* reports
PAUSED, IDLE, STALE_LOG, and NO_PROGRESS reason codes. Destructive recovery is
never inferred: checkpoint quarantine previews by default and requires
*--apply*.

# LIMITATIONS

OpenFOAM directives and code streams that foamlib cannot evaluate remain
best-effort. Real MPI lifecycle validation depends on a host that permits MPI
launcher sockets. Scheduler integration is not a supported generic interface.

# SEE ALSO

*foamDictionary*(1), *decomposePar*(1), *reconstructPar*(1), *mpirun*(1)

Project documentation: _docs/README.md_ and _docs/formats.md_.
