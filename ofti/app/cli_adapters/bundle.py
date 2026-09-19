from __future__ import annotations

import argparse
import shlex
import time
from pathlib import Path
from typing import cast

from ofti.app.cli_help import emit_json
from ofti.core import bundle_set, case_bundle
from ofti.core import run_manifest as manifest_ops
from ofti.foam.config import get_config
from ofti.plugins import PluginRegistry, discover_plugins
from ofti.tools import table_render_service
from ofti.tools.cli_tools import run as run_ops


def _bundle_commands(
    groups: argparse._SubParsersAction[argparse.ArgumentParser],
    registry: PluginRegistry | None,
) -> argparse._SubParsersAction[argparse.ArgumentParser]:
    bundle = groups.add_parser(
        "bundle",
        help="Create or extract portable case archives",
        description="Create case or campaign archives, or safely extract either archive kind.",
    )
    bundle.set_defaults(plugin_registry=registry or discover_plugins())
    return bundle.add_subparsers(dest="bundle_command", required=True)


def _build_bundle_parser(
    groups: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    registry: PluginRegistry | None = None,
) -> None:
    cfg = get_config()
    commands = _bundle_commands(groups, registry)
    case = commands.add_parser(
        "case",
        help="Package one runnable case",
        description="Bundle the minimal files needed to move and run one OpenFOAM case on another host.",
    )
    case.add_argument(
        "case_dir",
        nargs="?",
        default=Path.cwd(),
        type=Path,
        help="Case directory to package (default: current directory)",
    )
    case.add_argument(
        "--output",
        "-o",
        required=True,
        type=Path,
        help="Archive path to write (gzip tar format; .tar.gz recommended)",
    )
    case.add_argument(
        "--mesh",
        choices=("auto", "include", "exclude", "include-polyMesh", "none"),
        default=cfg.bundle.mesh,
        help=(
            "Mesh handling: auto includes constant/polyMesh when present; "
            "include/include-polyMesh carries mesh files; exclude/none leaves "
            "mesh generation to target host"
        ),
    )
    case.add_argument(
        "--time",
        default=cfg.bundle.time,
        help="Start time directory to include, or 'latest'",
    )
    case.add_argument(
        "--run-manifest",
        type=Path,
        default=None,
        help="Embed this external OFTI run manifest instead of auto-discovering one in CASE",
    )
    case.add_argument(
        "--smoke",
        action="store_true",
        help="After writing the archive, extract it locally and run a bounded smoke test",
    )
    case.add_argument(
        "--smoke-iterations",
        type=int,
        default=cfg.bundle.smoke_iterations,
        help="Iterations for --smoke validation (default: config or 5)",
    )
    case.add_argument(
        "--smoke-timeout",
        default=cfg.bundle.smoke_timeout,
        help="Wall timeout for --smoke, e.g. 30s, 2m (default: config or 60s)",
    )
    case.add_argument(
        "--smoke-solver",
        default=None,
        help="Solver override for --smoke; defaults to controlDict application",
    )
    case.add_argument("--json", action="store_true", help="Print result as JSON")
    case.add_argument("--table", action="store_true", help="Print aligned summary table")
    case.set_defaults(func=_bundle_case)

    bundle_set_parser = commands.add_parser(
        "set",
        help="Package multiple runnable cases",
        description="Create one deterministic archive of independently verifiable OFTI case bundles.",
    )
    bundle_set_parser.add_argument(
        "cases",
        nargs="*",
        type=Path,
        help="Case directories to include; directory names must be unique",
    )
    bundle_set_parser.add_argument(
        "--cases-file",
        type=Path,
        default=None,
        help="One case path per line; blank lines and # comments are ignored",
    )
    bundle_set_parser.add_argument(
        "--cases-root",
        type=Path,
        default=Path.cwd(),
        help="Root for relative paths in --cases-file (default: current directory)",
    )
    bundle_set_parser.add_argument("--output", "-o", required=True, type=Path, help="Bundle-set archive to write")
    bundle_set_parser.add_argument("--name", default=None, help="Campaign name stored in the manifest")
    bundle_set_parser.add_argument(
        "--mesh",
        choices=("auto", "include", "exclude", "include-polyMesh", "none"),
        default=cfg.bundle.mesh,
        help="Mesh policy applied independently to every case (default: config or auto)",
    )
    bundle_set_parser.add_argument(
        "--time",
        default=cfg.bundle.time,
        help="Start time included from every case, or 'latest'",
    )
    bundle_set_parser.add_argument("--json", action="store_true", help="Print result as JSON")
    bundle_set_parser.add_argument("--table", action="store_true", help="Print aligned summary table")
    bundle_set_parser.set_defaults(func=_bundle_set)

    extract = commands.add_parser(
        "extract",
        help="Extract a case or set archive",
        description="Detect the archive kind, verify every manifest and hash, then restore its cases.",
    )
    extract.add_argument("archive", type=Path, help="Archive created by `ofti bundle case` or `ofti bundle set`")
    extract.add_argument(
        "--to",
        dest="destination",
        required=True,
        type=Path,
        help="Destination case directory to create or verify",
    )
    extract.add_argument(
        "--force",
        action="store_true",
        help="Allow a case archive to extract into a non-empty destination (not valid for sets)",
    )
    extract.add_argument(
        "--run",
        action="store_true",
        help="Run a restored case immediately (not valid for sets)",
    )
    extract.add_argument(
        "--solver",
        default=None,
        help="Solver override for --run; defaults to controlDict application",
    )
    extract.add_argument(
        "--background",
        action="store_true",
        help="With --run, launch in the background and register a normal watchable job",
    )
    extract.add_argument("--json", action="store_true", help="Print result as JSON")
    extract.add_argument("--table", action="store_true", help="Print aligned summary table")
    extract.set_defaults(func=_extract_bundle)


def _bundle_case(args: argparse.Namespace) -> int:
    output = _configured_bundle_path(Path(args.output))
    manifest = case_bundle.create_bundle(
        Path(args.case_dir),
        output,
        mesh=str(args.mesh),
        time=args.time,
        run_manifest=getattr(args, "run_manifest", None),
        extra_warnings=plugin_bundle_hints(
            Path(args.case_dir),
            registry=getattr(args, "plugin_registry", None),
        ),
    )
    payload: dict[str, object] = {
        "ok": True,
        "archive": str(output),
        "case_dir": str(Path(args.case_dir)),
        "manifest": case_bundle.manifest_payload(manifest),
        "requirements": case_bundle.environment_requirements(manifest),
        "next": f"ofti bundle extract {output} --to CASE_DIR",
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
        if manifest.run_manifest:
            print(f"Run manifest: {manifest.run_manifest}")
        _print_requirements(payload)
        _print_warnings(manifest.warnings)
        _print_bundle_smoke(payload)
        print(f"Next: {payload['next']}")
    return 0 if smoke_ok else 1


def _bundle_set(args: argparse.Namespace) -> int:
    output = _configured_bundle_path(Path(args.output))
    cases = [Path(case).expanduser().resolve() for case in args.cases]
    cases_file = getattr(args, "cases_file", None)
    if cases_file is not None:
        cases.extend(bundle_set.read_case_list(Path(cases_file), root=Path(args.cases_root)))
    manifest = bundle_set.create_bundle_set(
        cases,
        output,
        name=args.name,
        mesh=str(args.mesh),
        time=str(args.time),
        extra_warnings={
            case: plugin_bundle_hints(
                case,
                registry=getattr(args, "plugin_registry", None),
            )
            for case in cases
        },
    )
    payload: dict[str, object] = {
        "ok": True,
        "archive": str(output.resolve()),
        "manifest": bundle_set.manifest_payload(manifest),
        "next": shlex.join(["ofti", "bundle", "extract", str(output.resolve()), "--to", "CASE_SET"]),
    }
    if args.json:
        emit_json(payload, args)
    elif args.table:
        print("\n".join(table_render_service.bundle_set_table_lines(payload)))
    else:
        print(f"Bundle set written: {output.resolve()}")
        print(f"Name: {manifest.name}")
        print(f"Cases: {len(manifest.cases)}")
        for entry in manifest.cases:
            print(f"  {entry.name}: {entry.manifest.application} ({len(entry.manifest.files)} files)")
        print(f"Next: {payload['next']}")
    return 0


def _extract_bundle(args: argparse.Namespace) -> int:
    archive = Path(args.archive)
    if case_bundle.detect_bundle_kind(archive) == "set":
        return _extract_bundle_set(args)
    return _extract_case(args)


def _extract_case(args: argparse.Namespace) -> int:
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
    code = _run_extracted_case(args, destination, payload) if args.run else 0
    if args.json:
        emit_json(payload, args)
    elif args.table:
        print("\n".join(table_render_service.extracted_bundle_table_lines(payload)))
    else:
        print(f"Bundle extracted: {destination}")
        print(f"Files verified: {len(manifest.files)}")
        print(f"Start time: {manifest.start_time}")
        print(f"Solver: {manifest.application}")
        print(f"OpenFOAM header: {manifest.header_version}")
        _print_requirements(payload)
        _print_warnings(manifest.warnings)
        _print_extract_run_or_next(payload)
    return code


def _extract_bundle_set(args: argparse.Namespace) -> int:
    unsupported = [name for name in ("force", "run", "solver", "background") if getattr(args, name, False)]
    if unsupported:
        options = ", ".join(f"--{name}" for name in unsupported)
        raise ValueError(f"{options} only applies to case bundles")
    destination = _configured_case_destination(Path(args.destination))
    manifest = bundle_set.extract_bundle_set(Path(args.archive), destination)
    restored = [str((destination / entry.name).resolve()) for entry in manifest.cases]
    payload: dict[str, object] = {
        "ok": True,
        "archive": str(Path(args.archive)),
        "destination": str(destination.resolve()),
        "manifest": bundle_set.manifest_payload(manifest),
        "cases": restored,
        "next": shlex.join(["ofti", "run", "queue", *restored]),
    }
    if args.json:
        emit_json(payload, args)
    elif args.table:
        print("\n".join(table_render_service.extracted_bundle_set_table_lines(payload)))
    else:
        print(f"Bundle set extracted: {destination.resolve()}")
        print(f"Cases verified: {len(restored)}")
        for case in restored:
            print(f"  {case}")
        print(f"Next: {payload['next']}")
    return 0


def _run_extracted_case(
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
        options=manifest_ops.RunManifestOptions(
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
        ),
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


def plugin_bundle_hints(
    case_dir: Path,
    *,
    registry: PluginRegistry | None = None,
) -> tuple[str, ...]:
    selected = registry or discover_plugins()
    warnings: list[str] = []
    for provider in selected.bundle_hints.values():
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
            options=run_ops.SmokeOptions(
                solver=getattr(args, "smoke_solver", None),
                iterations=int(getattr(args, "smoke_iterations", 5)),
                timeout=timeout,
                output_root=root / "run",
                in_place=True,
                core_only=True,
            ),
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


def _print_extract_run_or_next(payload: dict[str, object]) -> None:
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


__all__ = ["_build_bundle_parser"]
