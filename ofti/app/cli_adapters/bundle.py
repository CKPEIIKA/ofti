from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import cast

from ofti.app.cli_help import emit_json
from ofti.core import case_bundle
from ofti.core import run_manifest as manifest_ops
from ofti.foam.config import get_config
from ofti.plugins import discover_plugins
from ofti.tools import table_render_service
from ofti.tools.cli_tools import run as run_ops


def _build_bundle_parser(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    cfg = get_config()
    bundle = groups.add_parser(
        "bundle",
        help="Create a portable case archive",
        description=(
            "Bundle the minimal files needed to move and run an OpenFOAM case "
            "on another host."
        ),
    )
    bundle.add_argument(
        "case_dir",
        nargs="?",
        default=Path.cwd(),
        type=Path,
        help="Case directory to package (default: current directory)",
    )
    bundle.add_argument(
        "--output",
        "-o",
        required=True,
        type=Path,
        help="Archive path to write (gzip tar format; .tar.gz recommended)",
    )
    bundle.add_argument(
        "--mesh",
        choices=("auto", "include", "exclude", "include-polyMesh", "none"),
        default=cfg.bundle.mesh,
        help=(
            "Mesh handling: auto includes constant/polyMesh when present; "
            "include/include-polyMesh carries mesh files; exclude/none leaves "
            "mesh generation to target host"
        ),
    )
    bundle.add_argument(
        "--time",
        default=cfg.bundle.time,
        help="Start time directory to include, or 'latest'",
    )
    bundle.add_argument(
        "--smoke",
        action="store_true",
        help="After writing the archive, unbundle it locally and run a bounded smoke test",
    )
    bundle.add_argument(
        "--smoke-iterations",
        type=int,
        default=cfg.bundle.smoke_iterations,
        help="Iterations for --smoke validation (default: config or 5)",
    )
    bundle.add_argument(
        "--smoke-timeout",
        default=cfg.bundle.smoke_timeout,
        help="Wall timeout for --smoke, e.g. 30s, 2m (default: config or 60s)",
    )
    bundle.add_argument(
        "--smoke-solver",
        default=None,
        help="Solver override for --smoke; defaults to controlDict application",
    )
    bundle.add_argument("--json", action="store_true", help="Print result as JSON")
    bundle.add_argument("--table", action="store_true", help="Print aligned summary table")
    bundle.set_defaults(func=_bundle_case)

    unbundle = groups.add_parser(
        "unbundle",
        help="Extract a portable case archive",
        description="Extract an OFTI case bundle and verify file hashes before use.",
    )
    unbundle.add_argument("archive", type=Path, help="Bundle archive created by `ofti bundle`")
    unbundle.add_argument(
        "--to",
        dest="destination",
        required=True,
        type=Path,
        help="Destination case directory to create or verify",
    )
    unbundle.add_argument(
        "--force",
        action="store_true",
        help="Allow extracting into a non-empty destination",
    )
    unbundle.add_argument(
        "--run",
        action="store_true",
        help="Run the restored case immediately through the normal solver service",
    )
    unbundle.add_argument(
        "--solver",
        default=None,
        help="Solver override for --run; defaults to controlDict application",
    )
    unbundle.add_argument(
        "--background",
        action="store_true",
        help="With --run, launch in the background and register a normal watchable job",
    )
    unbundle.add_argument("--json", action="store_true", help="Print result as JSON")
    unbundle.add_argument("--table", action="store_true", help="Print aligned summary table")
    unbundle.set_defaults(func=_unbundle_case)


def _bundle_case(args: argparse.Namespace) -> int:
    output = _configured_bundle_path(Path(args.output))
    manifest = case_bundle.create_bundle(
        Path(args.case_dir),
        output,
        mesh=str(args.mesh),
        time=args.time,
        extra_warnings=_plugin_bundle_hints(Path(args.case_dir)),
    )
    payload: dict[str, object] = {
        "ok": True,
        "archive": str(output),
        "case_dir": str(Path(args.case_dir)),
        "manifest": case_bundle.manifest_payload(manifest),
        "requirements": case_bundle.environment_requirements(manifest),
        "next": f"ofti unbundle {output} --to CASE_DIR",
    }
    smoke_ok = True
    if bool(getattr(args, "smoke", False)):
        smoke_payload = _smoke_bundle_archive(args, output)
        payload["smoke"] = smoke_payload
        smoke_ok = bool(smoke_payload.get("ok"))
        payload["ok"] = smoke_ok
    if args.json:
        emit_json(payload, args)
    elif args.table:
        print("\n".join(table_render_service.bundle_table_lines(payload)))
    else:
        print(f"Bundle written: {output}")
        print(f"Files: {len(manifest.files)}")
        print(f"Start time: {manifest.start_time}")
        print(f"Solver: {manifest.application}")
        print(f"OpenFOAM header: {manifest.header_version}")
        _print_requirements(payload)
        _print_warnings(manifest.warnings)
        _print_bundle_smoke(payload)
        print(f"Next: {payload['next']}")
    return 0 if smoke_ok else 1


def _unbundle_case(args: argparse.Namespace) -> int:
    destination = _configured_case_destination(Path(args.destination))
    manifest = case_bundle.extract_bundle(
        Path(args.archive),
        destination,
        force=bool(args.force),
    )
    payload: dict[str, object] = {
        "ok": True,
        "archive": str(Path(args.archive)),
        "case_dir": str(destination),
        "manifest": case_bundle.manifest_payload(manifest),
        "requirements": case_bundle.environment_requirements(manifest),
        "next": f"ofti run solver {destination}",
    }
    code = _run_unbundled_case(args, destination, payload) if args.run else 0
    if args.json:
        emit_json(payload, args)
    elif args.table:
        print("\n".join(table_render_service.unbundle_table_lines(payload)))
    else:
        print(f"Bundle extracted: {destination}")
        print(f"Files verified: {len(manifest.files)}")
        print(f"Start time: {manifest.start_time}")
        print(f"Solver: {manifest.application}")
        print(f"OpenFOAM header: {manifest.header_version}")
        _print_requirements(payload)
        _print_warnings(manifest.warnings)
        _print_unbundle_run_or_next(payload)
    return code


def _run_unbundled_case(
    args: argparse.Namespace,
    destination: Path,
    payload: dict[str, object],
) -> int:
    name, command = run_ops.solver_command(destination, solver=args.solver)
    background = bool(args.background)
    result = run_ops.execute_solver_case_command(
        destination,
        name,
        command,
        background=background,
    )
    command_text = run_ops.dry_run_command(command)
    manifest_path = manifest_ops.write_case_run_manifest(
        destination,
        name=name,
        command=command_text,
        background=background,
        detached=background,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        log_path=result.log_path,
        pid=result.pid,
        returncode=result.returncode,
        solver_name=args.solver or name,
    )
    payload["run"] = {
        "command": command_text,
        "returncode": result.returncode,
        "background": background,
        "pid": result.pid,
        "log": str(result.log_path) if result.log_path else None,
        "manifest": str(manifest_path),
    }
    payload["ok"] = result.returncode == 0
    return int(result.returncode)


def _plugin_bundle_hints(case_dir: Path) -> tuple[str, ...]:
    registry = discover_plugins()
    warnings: list[str] = []
    for provider in registry.bundle_hints.values():
        try:
            warnings.extend(provider.bundle_hints(case_dir))
        except Exception as exc:
            warnings.append(f"plugin bundle hints failed for {provider.name}: {exc}")
    return tuple(warnings)


def _smoke_bundle_archive(args: argparse.Namespace, archive: Path) -> dict[str, object]:
    timeout = run_ops.parse_duration_seconds(getattr(args, "smoke_timeout", "60s"))
    root = _bundle_smoke_root(archive)
    restored = root / "case"
    case_bundle.extract_bundle(archive, restored, force=False)
    return dict(
        run_ops.smoke_payload(
            restored,
            solver=getattr(args, "smoke_solver", None),
            iterations=int(getattr(args, "smoke_iterations", 5)),
            timeout=timeout,
            output_root=root / "run",
            in_place=True,
            core_only=True,
        ),
    )


def _bundle_smoke_root(archive: Path) -> Path:
    safe_name = archive.name.replace("/", "_").replace(".tar.gz", "")
    smoke_root = get_config().paths.smoke_root
    if smoke_root:
        return Path(smoke_root).expanduser() / f"{safe_name}-{time.time_ns()}"
    return archive.resolve().parent / ".ofti" / "bundle-smoke" / f"{safe_name}-{time.time_ns()}"


def _configured_bundle_path(output: Path) -> Path:
    cfg = get_config()
    root = cfg.bundle.output_dir or cfg.paths.bundle_output_dir
    if root and not output.is_absolute():
        return Path(root).expanduser() / output
    return output


def _configured_case_destination(destination: Path) -> Path:
    root = get_config().paths.case_root
    if root and not destination.is_absolute():
        return Path(root).expanduser() / destination
    return destination


def _print_bundle_smoke(payload: dict[str, object]) -> None:
    raw_smoke = payload.get("smoke")
    if not isinstance(raw_smoke, dict):
        return
    smoke = cast(dict[str, object], raw_smoke)
    print(f"Smoke ok: {smoke.get('ok')} returncode={smoke.get('returncode')}")
    if smoke.get("case"):
        print(f"Smoke case: {smoke['case']}")
    if smoke.get("log_path"):
        print(f"Smoke log: {smoke['log_path']}")


def _print_unbundle_run_or_next(payload: dict[str, object]) -> None:
    raw_run = payload.get("run")
    if not isinstance(raw_run, dict):
        print(f"Next: {payload['next']}")
        return
    run = cast(dict[str, object], raw_run)
    print(f"Run return code: {run.get('returncode')}")
    if run.get("pid"):
        print(f"Run pid: {run['pid']}")
    if run.get("log"):
        print(f"Run log: {run['log']}")
    if run.get("manifest"):
        print(f"Run manifest: {run['manifest']}")


def _print_requirements(payload: dict[str, object]) -> None:
    raw = payload.get("requirements")
    if not isinstance(raw, dict):
        return
    requirements = cast(dict[str, object], raw)
    print("Target requirements:")
    print(f"  solver: {requirements.get('solver')}")
    print(f"  OpenFOAM header: {requirements.get('openfoam_header')}")
    print(f"  start time: {requirements.get('start_time')}")
    print(f"  mesh included: {requirements.get('mesh_included')}")
    notes = requirements.get("notes")
    if isinstance(notes, list):
        for note in notes:
            print(f"  note: {note}")


def _print_warnings(warnings: tuple[str, ...]) -> None:
    for warning in warnings:
        print(f"Warning: {warning}")


__all__ = ["_build_bundle_parser", "_bundle_case", "_unbundle_case"]
