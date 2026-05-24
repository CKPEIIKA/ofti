from __future__ import annotations

import argparse
from collections.abc import Callable

Handler = Callable[[argparse.Namespace], int]
_EASY_ON_CPU_TAIL_BYTES = 256 * 1024
_EASY_ON_CPU_MIN_POLL_INTERVAL = 1.0


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
    "receipt": "Run receipt JSON file",
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
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for subparser in action.choices.values():
                _fill_missing_help(subparser)
            continue
        if action.dest == "help" or action.help is not None:
            continue
        action.help = _HELP_BY_DEST.get(action.dest, action.dest.replace("_", " ").capitalize())

