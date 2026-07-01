from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from textwrap import dedent
from typing import TextIO

from ofti.core.output_contract import command_name, stamp_payload

Handler = Callable[[argparse.Namespace], int]
_EASY_ON_CPU_TAIL_BYTES = 256 * 1024
_EASY_ON_CPU_MIN_POLL_INTERVAL = 1.0

def emit_json(payload: object, args: argparse.Namespace, *, file: TextIO | None = None) -> None:
    """Print a JSON payload through the shared output contract.

    Stamps dict payloads with schema_version/command (see
    ``ofti.core.output_contract``). Pass ``file=sys.stderr`` for machine-readable
    error output.
    """
    stamped = stamp_payload(payload, command_name(args))
    print(json.dumps(stamped, indent=2, sort_keys=True), file=file)


def _help_handler(parser: argparse.ArgumentParser) -> Handler:
    def _show_help(_args: argparse.Namespace) -> int:
        parser.print_help()
        return 0

    return _show_help


def _add_easy_on_cpu_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--easy-on-cpu",
        action="store_true",
        help="Reduce CPU load with bounded log reads (can be combined with --fast/--full)",
    )
    # Backward-compatible alias.
    parser.add_argument(
        "--lightweight",
        dest="easy_on_cpu",
        action="store_true",
        help=argparse.SUPPRESS,
    )


def _add_table_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--table",
        action="store_true",
        help="Print aligned human-readable tables",
    )


def _output_mode_conflict(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False) and getattr(args, "table", False))


_HELP_BY_DEST = {
    "all": "Apply to all matching tracked jobs",
    "background": "Start the command in the background",
    "best": "Number of best-ranked cases to keep",
    "brief": "Use compact watcher output",
    "case_dir": "OpenFOAM case directory (default: current directory)",
    "cases": "Explicit case directories",
    "destination": "Destination path",
    "detailed": "Use detailed watcher output",
    "drag_band_limit": "Maximum allowed drag-band spread",
    "dry_run": "Print planned actions without applying them",
    "field": "Residual field to include (repeatable)",
    "follow": "Keep following the log for new lines",
    "format": "Output format",
    "glob": "Case directory glob",
    "job_id": "Tracked job id from .ofti/jobs.json",
    "json": "Print result as JSON",
    "kind": "Tracked job kind filter",
    "left_case": "Left case directory",
    "limit": "Maximum residual rows per field (0 means no limit)",
    "lines": "Number of log lines to print",
    "list": "List available tools",
    "log_file": "Log file path for background execution",
    "mass_limit": "Maximum allowed mass-balance drift",
    "max_parallel": "Maximum number of cases to run at once",
    "mode": "ETA target mode",
    "mpi": "MPI launcher (default: mpirun/mpiexec)",
    "name": "Tool or tracked job name",
    "no_detach": "Run foreground even when background flags are present",
    "output": "Output verbosity",
    "output_root": "Directory for generated cases",
    "parallel": "Number of MPI ranks / subdomains (0 means serial)",
    "pid_file": "Write background process pid to this file",
    "poll_interval": "Seconds between queue status polls",
    "manifest": "Run manifest JSON file",
    "right_case": "Right case directory",
    "seconds": "Polling interval in seconds",
    "set_dir": "Case-set root used when explicit cases are omitted",
    "shock_drift_limit": "Maximum allowed shock-position drift",
    "solver": "Solver override; defaults to controlDict application",
    "source": "Case directory or solver log path",
    "startup_samples": "Samples to ignore before stability checks",
    "summary_csv": "Read case paths from a campaign summary CSV",
    "tail_bytes": "Max solver log bytes to parse",
    "tolerance": "Required stability tolerance",
    "window": "Number of recent samples to inspect",
    "worst": "Number of worst-ranked cases to stop",
}


def _fill_missing_help(parser: argparse.ArgumentParser) -> None:
    _fill_parser_examples(parser)
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for subparser in action.choices.values():
                _fill_missing_help(subparser)
            continue
        if action.dest == "help" or action.help is not None:
            continue
        action.help = _HELP_BY_DEST.get(action.dest, action.dest.replace("_", " ").capitalize())


def _fill_parser_examples(parser: argparse.ArgumentParser) -> None:
    if parser.epilog:
        return
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = _EXAMPLES_BY_PROG.get(parser.prog, _generic_examples(parser.prog))


def _generic_examples(prog: str) -> str:
    for prefix, lines in _GENERIC_EXAMPLE_PREFIXES:
        if prog.startswith(prefix):
            return _examples(*(line.format(prog=prog) for line in lines))
    return _examples(f"{prog} -h")


def _examples(*lines: str) -> str:
    return "Examples:\n" + "\n".join(f"  {line}" for line in lines)


_GENERIC_EXAMPLE_PREFIXES = (
    ("ofti version", ("ofti version", "ofti -V")),
    ("ofti knife campaign", ("{prog} --set CASE_SET --json", "{prog} CASE_A CASE_B --table")),
    ("ofti knife manifest", ("{prog} CASE --json", "{prog} CASE --table")),
    ("ofti knife", ("{prog} CASE --json", "{prog} CASE --table")),
    ("ofti watch", ("{prog} CASE --json", "{prog} CASE --easy-on-cpu")),
    ("ofti run", ("{prog} CASE --json", "{prog} CASE --dry-run")),
    ("ofti plot", ("{prog} CASE --table", "{prog} CASE --json")),
)


_EXAMPLES_BY_PROG = {
    "ofti knife": dedent(
        """\
        Examples:
          ofti knife preflight CASE --json
          ofti knife status CASE --table
          ofti knife physical CASE --field rho:min=0 --fail-on-bad
        """,
    ),
    "ofti knife doctor": _examples("ofti knife doctor CASE", "ofti knife doctor CASE --json"),
    "ofti knife preflight": _examples(
        "ofti knife preflight CASE",
        "ofti knife preflight CASE --json",
    ),
    "ofti knife compare": dedent(
        """\
        Examples:
          ofti knife compare LEFT_CASE RIGHT_CASE
          ofti knife compare LEFT_CASE RIGHT_CASE --json
        """,
    ),
    "ofti knife physical": dedent(
        """\
        Examples:
          ofti knife physical CASE --time latest --fields p,U,rho,T --json
          ofti knife physical CASE --field rho:min=0 --field T:min=0 --fail-on-bad
        """,
    ),
    "ofti knife compare-fields": dedent(
        """\
        Examples:
          ofti knife compare-fields SERIAL_CASE PARALLEL_CASE --preset flow --json
          ofti knife compare-fields CASE_A CASE_B --fields p,U,rho --time latest
        """,
    ),
    "ofti knife copy": _examples(
        "ofti knife copy DEST --case CASE",
        "ofti knife copy DEST --case CASE --json",
    ),
    "ofti knife manifest": dedent(
        """\
        Examples:
          ofti knife manifest write CASE --json
          ofti knife manifest verify runs/manifest.json --json
          ofti knife manifest restore runs/manifest.json --to restored-case
        """,
    ),
    "ofti knife manifest write": _examples("ofti knife manifest write CASE --json"),
    "ofti knife manifest verify": _examples(
        "ofti knife manifest verify runs/manifest.json --json",
    ),
    "ofti knife manifest restore": dedent(
        """\
        Examples:
          ofti knife manifest restore runs/manifest.json --to restored-case
          ofti knife manifest restore runs/manifest.json --to restored-case --force
        """,
    ),
    "ofti knife current": _examples("ofti knife current --root . --recursive --table"),
    "ofti knife adopt": _examples("ofti knife adopt --root . --all-untracked --json"),
    "ofti knife set": _examples("ofti knife set CASE system/controlDict endTime 10"),
    "ofti knife stop": _examples(
        "ofti knife stop CASE --all",
        "ofti knife stop CASE --signal TERM",
    ),
    "ofti run": dedent(
        """\
        Examples:
          ofti run solver CASE --dry-run --json
          ofti run solver CASE --background --write-manifest
          ofti run queue CASE_A CASE_B --max-parallel 1 --json
        """,
    ),
    "ofti run tool": _examples(
        "ofti run tool --list --case CASE",
        "ofti run tool blockMesh --case CASE",
    ),
    "ofti run solver": dedent(
        """\
        Examples:
          ofti run solver CASE --dry-run --json
          ofti run solver CASE --background --write-manifest
          ofti run solver CASE --parallel 4 --clean-processors
        """,
    ),
    "ofti run smoke": _examples("ofti run smoke CASE --iterations 20 --timeout 5m --json"),
    "ofti run resize-parallel": _examples(
        "ofti run resize-parallel CASE --to 8 --dry-run --table",
    ),
    "ofti run matrix": _examples(
        "ofti run matrix CASE --param application=simpleFoam,pisoFoam --no-launch --json",
    ),
    "ofti run parametric": _examples(
        "ofti run parametric CASE --entry application --values simpleFoam,pisoFoam",
    ),
    "ofti run queue": _examples("ofti run queue CASE_A CASE_B --max-parallel 1 --json"),
    "ofti run queue-summary": _examples(
        "ofti run queue-summary .ofti/queues/queue-123.json",
        "ofti run queue-summary .ofti/queues/queue-123.events.jsonl --json",
    ),
    "ofti run status": _examples(
        "ofti run status --set CASE_SET --json",
        "ofti run status CASE --table",
    ),
    "ofti watch": dedent(
        """\
        Examples:
          ofti watch jobs CASE --table
          ofti watch log CASE --lines 80
          ofti watch stop CASE --signal TERM
        """,
    ),
    "ofti watch jobs": _examples(
        "ofti watch jobs CASE --table",
        "ofti watch jobs CASE --json",
    ),
    "ofti watch log": _examples(
        "ofti watch log CASE --lines 80",
        "ofti watch log CASE --follow --easy-on-cpu",
    ),
    "ofti watch attach": _examples("ofti watch attach CASE --lines 80"),
    "ofti watch start": _examples("ofti watch start CASE --background --write-manifest"),
    "ofti watch stop": _examples(
        "ofti watch stop CASE --all",
        "ofti watch stop CASE --signal TERM",
    ),
    "ofti watch external": _examples("ofti watch external CASE --json"),
    "ofti plot": _examples(
        "ofti plot metrics CASE --table",
        "ofti plot residuals CASE --json",
    ),
    "ofti plot metrics": _examples("ofti plot metrics CASE --table"),
    "ofti plot criteria": _examples("ofti plot criteria CASE --table"),
    "ofti plot residuals": _examples("ofti plot residuals CASE --json"),
    "ofti bundle": dedent(
        """\
        Examples:
          ofti bundle CASE --output case.ofti.tar.gz --mesh auto --time 0
          ofti bundle CASE --output case.ofti.tar.gz --mesh include-polyMesh --table
          ofti bundle CASE --output case.ofti.tar.gz --smoke --smoke-timeout 60s

        Bundle intent:
          Create the smallest portable archive that can run elsewhere: system/,
          constant/, the selected start-time directory, Allrun/Allclean when
          present, OFTI metadata, and mesh files when --mesh auto/include needs
          them. The aliases include-polyMesh and none are accepted but v1
          manifests keep canonical auto/include/exclude values. Logs,
          processor* directories, postProcessing, and caches are excluded. Add
          --smoke to prove the archive can be unbundled and run on the current
          host before copying it elsewhere.
        """,
    ),
    "ofti unbundle": dedent(
        """\
        Examples:
          ofti unbundle case.ofti.tar.gz --to CASE_COPY
          ofti unbundle case.ofti.tar.gz --to CASE_COPY --table
          ofti unbundle case.ofti.tar.gz --to CASE_COPY --run --background --json

        Target-host workflow:
          Copy archive to another host, run unbundle there, then use --run (or
          the printed `ofti run solver ...` command). Extraction verifies hashes
          and refuses non-empty destinations unless --force is used.
        """,
    ),
}
