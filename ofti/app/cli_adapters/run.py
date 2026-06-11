from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from ofti.app.cli_adapters.run_cases import (  # noqa: F401
    _run_matrix,
    _run_parametric,
    _run_queue,
    _run_status,
)
from ofti.app.cli_adapters.run_parser import RunHandlers, add_parser  # noqa: F401
from ofti.tools import parallel_resize_service, table_render_service
from ofti.tools import run_manifest_service as manifest_ops
from ofti.tools.cli_tools import run as run_ops

_EASY_ON_CPU_TAIL_BYTES = 256 * 1024
_EASY_ON_CPU_MIN_POLL_INTERVAL = 1.0


def _run_use_easy_on_cpu_mode(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "easy_on_cpu", False))


def _tail_bytes_with_cpu_mode(args: argparse.Namespace) -> int | None:
    explicit = getattr(args, "tail_bytes", None)
    if explicit is not None:
        return int(explicit)
    if _run_use_easy_on_cpu_mode(args):
        return _EASY_ON_CPU_TAIL_BYTES
    return None


def _interval_with_cpu_mode(args: argparse.Namespace, interval: float) -> float:
    if not _run_use_easy_on_cpu_mode(args):
        return interval
    return max(float(interval), _EASY_ON_CPU_MIN_POLL_INTERVAL)





def _run_tool(args: argparse.Namespace) -> int:
    if args.list:
        return _print_tool_catalog(args)
    if not args.name:
        raise ValueError("tool name is required unless --list is used")
    resolved = run_ops.resolve_tool(args.case_dir, args.name)
    if resolved is None:
        return _print_unknown_tool(args)
    display_name, cmd = resolved
    result = run_ops.execute_case_command(
        args.case_dir,
        display_name,
        cmd,
        background=bool(args.background),
    )
    return _print_tool_result(args, display_name, cmd, result)


def _print_tool_catalog(args: argparse.Namespace) -> int:
    payload = run_ops.tool_catalog_payload(args.case_dir)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.tool_catalog_table_lines(payload)))
        return 0
    for name in payload["tools"]:
        print(name)
    return 0


def _print_unknown_tool(args: argparse.Namespace) -> int:
    names = run_ops.tool_catalog_names(args.case_dir)
    available = ", ".join(names)
    if args.json:
        payload: dict[str, object] = {
            "error": "unknown tool",
            "requested": args.name,
            "available": names,
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(f"Unknown tool: {args.name}", file=sys.stderr)
    if available:
        print(f"Available tools: {available}", file=sys.stderr)
    return 1


def _print_tool_result(
    args: argparse.Namespace,
    display_name: str,
    cmd: list[str],
    result: object,
) -> int:
    if args.json:
        payload = _tool_result_payload(args, display_name, cmd, result)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return int(result.returncode)
    pid = result.pid
    log_path = result.log_path
    if pid is not None:
        print(f"Started {display_name} in background: pid={pid} log={log_path}")
        return 0
    stdout = result.stdout
    stderr = result.stderr
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, file=sys.stderr, end="")
    return int(result.returncode)


def _tool_result_payload(
    args: argparse.Namespace,
    display_name: str,
    cmd: list[str],
    result: object,
) -> dict[str, object]:
    return {
        "case": str(Path(args.case_dir).resolve()),
        "name": display_name,
        "command": run_ops.dry_run_command(cmd),
        "background": bool(args.background),
        "returncode": result.returncode,
        "pid": result.pid,
        "log_path": str(result.log_path) if result.log_path else None,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _run_resize_parallel(args: argparse.Namespace) -> int:
    payload = parallel_resize_service.parallel_resize_payload(
        args.case_dir,
        to_ranks=int(args.to_ranks),
        from_ranks=getattr(args, "from_ranks", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        start=bool(getattr(args, "start", True)),
        write_now=bool(getattr(args, "write_now", True)),
        force_stop=bool(getattr(args, "force_stop", False)),
        clean_processors=bool(getattr(args, "clean_processors", True)),
        stop_timeout=float(getattr(args, "timeout", 45.0)),
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload.get("ok") else 1
    if bool(getattr(args, "table", False)):
        print("\n".join(table_render_service.parallel_resize_table_lines(payload)))
        return 0 if payload.get("ok") else 1
    for line in table_render_service.parallel_resize_table_lines(payload):
        print(line)
    return 0 if payload.get("ok") else 1


def _run_solver(args: argparse.Namespace) -> int:
    return _run_solver_with_mode(args, background=bool(args.background))


def _run_solver_with_mode(args: argparse.Namespace, *, background: bool) -> int:
    sync_subdomains = bool(getattr(args, "sync_subdomains", True))
    clean_processors = bool(getattr(args, "clean_processors", False))
    prepare_parallel = bool(getattr(args, "prepare_parallel", True))
    parallel = int(getattr(args, "parallel", 0))
    display, cmd = run_ops.solver_command(
        args.case_dir,
        solver=args.solver,
        parallel=parallel,
        mpi=args.mpi,
        sync_subdomains=sync_subdomains,
    )
    if getattr(args, "dry_run", False):
        return _run_solver_dry_run(
            args,
            display=display,
            cmd=cmd,
            parallel=parallel,
            sync_subdomains=sync_subdomains,
            clean_processors=clean_processors,
            prepare_parallel=prepare_parallel,
        )
    return _run_solver_execute(
        args,
        background=background,
        display=display,
        cmd=cmd,
        parallel=parallel,
        sync_subdomains=sync_subdomains,
        clean_processors=clean_processors,
        prepare_parallel=prepare_parallel,
    )


def _run_solver_dry_run(
    args: argparse.Namespace,
    *,
    display: str,
    cmd: list[str],
    parallel: int,
    sync_subdomains: bool,
    clean_processors: bool,
    prepare_parallel: bool,
) -> int:
    parallel_setup = _parallel_setup_payload(
        args.case_dir,
        cmd=cmd,
        parallel=parallel,
        clean_processors=clean_processors,
        prepare_parallel=prepare_parallel,
        dry_run=True,
        extra_env=None,
    )
    cmd_text = run_ops.dry_run_command(cmd)
    write_manifest = _write_manifest_enabled(args)
    manifest_path = (
        _planned_manifest_path(args.case_dir, getattr(args, "receipt_file", None))
        if write_manifest
        else None
    )
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "case": str(Path(args.case_dir).resolve()),
                    "name": display,
                    "command": cmd_text,
                    "dry_run": True,
                    "sync_subdomains": sync_subdomains,
                    "clean_processors": clean_processors,
                    "prepare_parallel": prepare_parallel,
                    "write_manifest": write_manifest,
                    "write_receipt": write_manifest,
                    "record_inputs_copy": bool(getattr(args, "record_inputs_copy", False)),
                    "manifest_path": str(manifest_path) if manifest_path is not None else None,
                    "receipt_path": str(manifest_path) if manifest_path is not None else None,
                    "parallel_setup": parallel_setup,
                },
                indent=2,
                sort_keys=True,
            ),
        )
        return 0
    print(cmd_text)
    if parallel_setup is not None:
        print(
            f"# pre: decompose={parallel_setup.get('decompose_command')} "
            f"clean_processors={clean_processors}",
        )
    elif parallel > 1 and "-parallel" in cmd:
        print("# pre: skipped (--no-prepare-parallel)")
    if manifest_path is not None:
        print(f"# manifest: {manifest_path}")
    return 0


def _run_solver_execute(
    args: argparse.Namespace,
    *,
    background: bool,
    display: str,
    cmd: list[str],
    parallel: int,
    sync_subdomains: bool,
    clean_processors: bool,
    prepare_parallel: bool,
) -> int:
    detached = not bool(getattr(args, "no_detach", False))
    log_path_raw = getattr(args, "log_file", None)
    pid_path_raw = getattr(args, "pid_file", None)
    log_path = Path(log_path_raw) if isinstance(log_path_raw, str) and log_path_raw else None
    pid_path = Path(pid_path_raw) if isinstance(pid_path_raw, str) and pid_path_raw else None
    extra_env = _parse_env_assignments(getattr(args, "env", []))
    write_manifest = _write_manifest_enabled(args)
    manifest_output = (
        _planned_manifest_path(args.case_dir, getattr(args, "receipt_file", None))
        if write_manifest
        else None
    )
    parallel_setup = _parallel_setup_payload(
        args.case_dir,
        cmd=cmd,
        parallel=parallel,
        clean_processors=clean_processors,
        prepare_parallel=prepare_parallel,
        dry_run=False,
        extra_env=extra_env,
    )
    result = run_ops.execute_solver_case_command(
        args.case_dir,
        display,
        cmd,
        parallel=parallel,
        mpi=args.mpi,
        background=background,
        detached=detached,
        log_path=log_path,
        pid_path=pid_path,
        extra_env=extra_env,
    )
    written_manifest: Path | None = None
    if write_manifest:
        written_manifest = manifest_ops.write_case_run_manifest(
            Path(args.case_dir),
            name=display,
            command=run_ops.dry_run_command(cmd),
            background=background,
            detached=detached if background else False,
            parallel=parallel,
            mpi=args.mpi,
            sync_subdomains=sync_subdomains,
            prepare_parallel=prepare_parallel,
            clean_processors=clean_processors,
            extra_env=extra_env,
            log_path=result.log_path,
            pid=result.pid,
            returncode=result.returncode,
            output=manifest_output,
            record_inputs_copy=bool(getattr(args, "record_inputs_copy", False)),
            solver_name=_solver_name_for_manifest(cmd, parallel=parallel),
        )
    if getattr(args, "json", False):
        payload: dict[str, object] = {
            "case": str(Path(args.case_dir).resolve()),
            "name": display,
            "command": run_ops.dry_run_command(cmd),
            "background": background,
            "detached": detached if background else False,
            "log_file": str(log_path) if log_path is not None else None,
            "pid_file": str(pid_path) if pid_path is not None else None,
            "env": extra_env,
            "sync_subdomains": sync_subdomains,
            "clean_processors": clean_processors,
            "prepare_parallel": prepare_parallel,
            "write_manifest": write_manifest,
            "write_receipt": write_manifest,
            "record_inputs_copy": bool(getattr(args, "record_inputs_copy", False)),
            "manifest_path": str(written_manifest) if written_manifest is not None else None,
            "receipt_path": str(written_manifest) if written_manifest is not None else None,
            "parallel_setup": parallel_setup,
            "returncode": result.returncode,
            "pid": result.pid,
            "log_path": str(result.log_path) if result.log_path else None,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "dry_run": False,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return result.returncode
    if result.pid is not None:
        print(f"Started {display} in background: pid={result.pid} log={result.log_path}")
        if written_manifest is not None:
            print(f"Receipt: {written_manifest}")
        return 0
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if written_manifest is not None:
        print(f"Receipt: {written_manifest}")
    return result.returncode


def _parallel_setup_payload(
    case_dir: Path,
    *,
    cmd: list[str],
    parallel: int,
    clean_processors: bool,
    prepare_parallel: bool,
    dry_run: bool,
    extra_env: dict[str, str] | None,
) -> dict[str, object] | None:
    if not (parallel > 1 and "-parallel" in cmd and prepare_parallel):
        return None
    return cast(
        "dict[str, object]",
        run_ops.prepare_parallel_case(
            case_dir,
            parallel=parallel,
            clean_processors=clean_processors,
            extra_env=extra_env,
            dry_run=dry_run,
        ),
    )


def _write_manifest_enabled(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "write_receipt", False)
        or getattr(args, "record_inputs_copy", False)
        or getattr(args, "receipt_file", None) is not None,
    )


def _planned_manifest_path(case_dir: Path, receipt_file: object) -> Path:
    output = receipt_file if isinstance(receipt_file, Path) else None
    return manifest_ops.resolve_manifest_output(Path(case_dir), output)


def _solver_name_for_manifest(cmd: list[str], *, parallel: int) -> str | None:
    solver = run_ops._solver_token_from_command(cmd, parallel=parallel)
    return str(solver) if solver else None


def _parse_env_assignments(raw_values: object) -> dict[str, str]:
    values: list[str] = []
    if isinstance(raw_values, list):
        values = [str(item) for item in raw_values]
    payload: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"invalid --env assignment: {item}")
        key, value = item.split("=", 1)
        name = key.strip()
        if not name:
            raise ValueError(f"invalid --env assignment: {item}")
        payload[name] = value
    return payload
