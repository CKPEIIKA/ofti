from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Handler = Callable[[argparse.Namespace], int]


@dataclass(frozen=True)
class RunHandlers:
    tool: Handler
    resize_parallel: Handler
    solver: Handler
    matrix: Handler
    parametric: Handler
    queue: Handler
    status: Handler


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


def add_parser(
    groups: argparse._SubParsersAction[argparse.ArgumentParser],
    handlers: RunHandlers,
) -> None:
    run = groups.add_parser(
        "run",
        help="Run solver/tools outside the TUI",
        description=(
            "Run solver/tools outside the TUI.\n"
            "Tool names come from built-ins plus case-local presets from ofti.tools."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run.set_defaults(func=_help_handler(run))
    run_sub = run.add_subparsers(dest="command", required=False)

    tool = run_sub.add_parser("tool", help="Run a tool from the OFTI tool catalog")
    tool.add_argument("name", nargs="?")
    tool.add_argument("--case", dest="case_dir", default=Path.cwd(), type=Path)
    tool.add_argument("--list", action="store_true")
    tool.add_argument("--background", action="store_true")
    _add_table_flag(tool)
    tool.add_argument("--json", action="store_true", help="Print result as JSON")
    tool.set_defaults(func=handlers.tool)

    resize = run_sub.add_parser(
        "resize-parallel",
        help="Safely migrate a parallel case from one MPI size to another",
        description=(
            "Request writeNow, wait for solver stop, reconstruct latest time, clean old "
            "processor directories, update decomposeParDict, decompose latest time, "
            "and optionally restart with the new MPI rank count."
        ),
    )
    resize.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    resize.add_argument("--from", dest="from_ranks", type=int, default=None)
    resize.add_argument("--to", dest="to_ranks", type=int, required=True)
    resize.add_argument("--timeout", type=float, default=45.0)
    resize.add_argument("--dry-run", action="store_true")
    resize.add_argument("--no-start", dest="start", action="store_false", default=True)
    resize.add_argument("--no-write-now", dest="write_now", action="store_false", default=True)
    resize.add_argument("--force-stop", action="store_true")
    resize.add_argument(
        "--clean-processors",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Remove old processor* directories before decomposing to --to",
    )
    _add_table_flag(resize)
    resize.add_argument("--json", action="store_true")
    resize.set_defaults(func=handlers.resize_parallel)

    solver = run_sub.add_parser("solver", help="Run the solver from controlDict application")
    solver.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    solver.add_argument("--solver", default=None)
    solver.add_argument("--parallel", type=int, default=0)
    solver.add_argument("--mpi", default=None, help="MPI launcher (default: mpirun/mpiexec)")
    solver.add_argument(
        "--sync-subdomains",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For parallel runs, sync decomposeParDict numberOfSubdomains to --parallel",
    )
    solver.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    solver.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    solver.add_argument("--background", action="store_true")
    solver.add_argument("--no-detach", action="store_true")
    solver.add_argument("--log-file", default=None)
    solver.add_argument("--pid-file", default=None)
    solver.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    solver.add_argument(
        "--write-receipt",
        "--write-manifest",
        dest="write_receipt",
        action="store_true",
        help="Write immutable launch manifest under ./runs/",
    )
    solver.add_argument(
        "--record-inputs-copy",
        action="store_true",
        help="Copy system/, constant/, and 0/ alongside the receipt for restore",
    )
    solver.add_argument(
        "--receipt-file",
        "--manifest-file",
        dest="receipt_file",
        default=None,
        type=Path,
        help="Manifest/receipt JSON path (relative paths resolve from current working directory)",
    )
    solver.add_argument("--dry-run", action="store_true")
    solver.add_argument("--json", action="store_true", help="Print result as JSON")
    solver.set_defaults(func=handlers.solver)

    matrix = run_sub.add_parser(
        "matrix",
        help="Generate matrix cases from parameter axes and optionally launch them",
    )
    matrix.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    matrix.add_argument(
        "--param",
        action="append",
        default=[],
        help=(
            "Matrix axis: [DICT:]ENTRY=v1,v2. "
            "Examples: application=simpleFoam,pisoFoam "
            "or constant/chemistryProperties:modifiedTemperature=on,off"
        ),
    )
    matrix.add_argument(
        "--dict",
        dest="default_dict",
        default="system/controlDict",
        help="Default dictionary path for --param axes without DICT:",
    )
    matrix.add_argument("--output-root", type=Path, default=None)
    matrix.add_argument("--solver", default=None)
    matrix.add_argument("--parallel", type=int, default=0)
    matrix.add_argument("--mpi", default=None)
    matrix.add_argument("--max-parallel", type=int, default=1)
    matrix.add_argument("--poll-interval", type=float, default=0.25)
    _add_easy_on_cpu_flag(matrix)
    matrix.add_argument(
        "--backend",
        choices=["process", "foamlib-async", "foamlib-slurm"],
        default="process",
        help="Queue backend used when launching generated cases",
    )
    matrix.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    matrix.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    matrix.add_argument("--dry-run", action="store_true")
    matrix.add_argument(
        "--no-launch",
        action="store_true",
        help="Generate cases only (do not launch solver queue)",
    )
    matrix.add_argument("--json", action="store_true", help="Print result as JSON")
    matrix.set_defaults(func=handlers.matrix)

    parametric = run_sub.add_parser(
        "parametric",
        help="Generate parametric cases (single/csv/grid) and optionally launch them",
    )
    parametric.add_argument("case_dir", nargs="?", default=Path.cwd(), type=Path)
    mode = parametric.add_mutually_exclusive_group()
    mode.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="CSV path for foamlib preprocessing study (relative to case or absolute)",
    )
    mode.add_argument(
        "--grid-axis",
        action="append",
        default=[],
        help="Grid axis: [DICT:]ENTRY=v1,v2 (repeatable)",
    )
    parametric.add_argument(
        "--dict",
        dest="dict_path",
        default="system/controlDict",
        help="Dictionary path for single-entry mode (default: system/controlDict)",
    )
    parametric.add_argument(
        "--entry",
        default=None,
        help="Dictionary entry for single-entry mode, e.g. application",
    )
    parametric.add_argument(
        "--values",
        action="append",
        default=[],
        help="Value list for single-entry mode (comma-separated, repeatable)",
    )
    parametric.add_argument("--output-root", type=Path, default=None)
    parametric.add_argument(
        "--run-solver",
        action="store_true",
        help="Run solver queue for generated cases",
    )
    parametric.add_argument("--solver", default=None)
    parametric.add_argument("--parallel", type=int, default=0)
    parametric.add_argument("--mpi", default=None)
    parametric.add_argument("--max-parallel", type=int, default=1)
    parametric.add_argument("--poll-interval", type=float, default=0.25)
    _add_easy_on_cpu_flag(parametric)
    parametric.add_argument(
        "--backend",
        choices=["process", "foamlib-async", "foamlib-slurm"],
        default="process",
        help="Queue backend used when --run-solver is enabled",
    )
    parametric.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    parametric.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    parametric.add_argument("--json", action="store_true", help="Print result as JSON")
    parametric.set_defaults(func=handlers.parametric)

    queue = run_sub.add_parser(
        "queue",
        help="Run a case set in batches with bounded parallelism",
    )
    queue.add_argument("cases", nargs="*", type=Path)
    queue.add_argument("--set", dest="set_dir", default=Path.cwd(), type=Path)
    queue.add_argument("--glob", default="*")
    queue.add_argument("--summary-csv", default=None, type=Path)
    queue.add_argument("--solver", default=None)
    queue.add_argument("--parallel", type=int, default=0)
    queue.add_argument("--mpi", default=None)
    queue.add_argument(
        "--backend",
        choices=["process", "foamlib-async", "foamlib-slurm"],
        default="process",
        help="Queue backend for case launches",
    )
    queue.add_argument("--max-parallel", type=int, required=True)
    queue.add_argument("--poll-interval", type=float, default=0.25)
    _add_easy_on_cpu_flag(queue)
    queue.add_argument(
        "--prepare-parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run parallel prelaunch step (optional clean + decomposePar -force)",
    )
    queue.add_argument(
        "--clean-processors",
        action="store_true",
        help="Remove stale processor* directories before parallel decompose",
    )
    queue.add_argument("--dry-run", action="store_true")
    queue.add_argument("--json", action="store_true", help="Print result as JSON")
    queue.set_defaults(func=handlers.queue)

    status = run_sub.add_parser(
        "status",
        help="Show compact status table for a case set",
        description=(
            "Show a compact read-only status table for explicit cases or for "
            "cases discovered under --set/--glob."
        ),
    )
    status.add_argument("cases", nargs="*", type=Path, help="Explicit case directories")
    status.add_argument(
        "--set",
        dest="set_dir",
        default=Path.cwd(),
        type=Path,
        help="Case-set root used when explicit cases are omitted",
    )
    status.add_argument("--glob", default="*", help="Case directory glob under --set")
    status.add_argument(
        "--summary-csv",
        default=None,
        type=Path,
        help="Read case paths from a campaign summary CSV",
    )
    status_mode = status.add_mutually_exclusive_group()
    status_mode.add_argument("--fast", action="store_true", help="Use lightweight status parsing")
    status_mode.add_argument("--full", action="store_true", help="Parse full logs (slower)")
    _add_easy_on_cpu_flag(status)
    status.add_argument(
        "--tail-bytes",
        type=int,
        default=None,
        help="Max solver log bytes to parse",
    )
    _add_table_flag(status)
    status.add_argument("--json", action="store_true", help="Print result as JSON")
    status.set_defaults(func=handlers.status)
