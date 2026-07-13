from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from ofti.app.cli_adapters.bundle import plugin_bundle_hints
from ofti.app.cli_help import emit_json
from ofti.core import bundle_set
from ofti.foam.config import get_config


def _build_bundle_set_parsers(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    cfg = get_config()
    create = groups.add_parser(
        "bundle-set",
        help="Package multiple runnable cases as one portable archive",
        description="Create one deterministic archive of independently verifiable OFTI case bundles.",
    )
    create.add_argument("cases", nargs="+", type=Path, help="Case directories to include; names must be unique")
    create.add_argument("--output", "-o", required=True, type=Path, help="Bundle-set archive to write (.tar.gz)")
    create.add_argument("--name", default=None, help="Campaign name stored in the manifest")
    create.add_argument(
        "--mesh",
        choices=("auto", "include", "exclude", "include-polyMesh", "none"),
        default=cfg.bundle.mesh,
        help="Mesh policy applied independently to every case (default: config or auto)",
    )
    create.add_argument("--time", default=cfg.bundle.time, help="Start time included from every case, or 'latest'")
    create.add_argument("--json", action="store_true", help="Print result as JSON")
    create.set_defaults(func=_bundle_set)

    extract = groups.add_parser(
        "unbundle-set",
        help="Extract and verify a portable case collection",
        description="Verify every embedded case bundle, then restore cases under one destination directory.",
    )
    extract.add_argument("archive", type=Path, help="Archive created by `ofti bundle-set`")
    extract.add_argument("--to", dest="destination", required=True, type=Path, help="Empty destination root")
    extract.add_argument("--json", action="store_true", help="Print result as JSON")
    extract.set_defaults(func=_unbundle_set)


def _bundle_set(args: argparse.Namespace) -> int:
    output = _configured_output(Path(args.output))
    cases = [Path(case).expanduser().resolve() for case in args.cases]
    manifest = bundle_set.create_bundle_set(
        cases,
        output,
        name=args.name,
        mesh=str(args.mesh),
        time=str(args.time),
        extra_warnings={case: plugin_bundle_hints(case) for case in cases},
    )
    payload: dict[str, object] = {
        "ok": True,
        "archive": str(output.resolve()),
        "manifest": bundle_set.manifest_payload(manifest),
        "next": shlex.join(["ofti", "unbundle-set", str(output.resolve()), "--to", "CASE_SET"]),
    }
    if args.json:
        emit_json(payload, args)
    else:
        print(f"Bundle set written: {output.resolve()}")
        print(f"Name: {manifest.name}")
        print(f"Cases: {len(manifest.cases)}")
        for entry in manifest.cases:
            print(f"  {entry.name}: {entry.manifest.application} ({len(entry.manifest.files)} files)")
        print(f"Next: {payload['next']}")
    return 0


def _unbundle_set(args: argparse.Namespace) -> int:
    destination = _configured_destination(Path(args.destination))
    manifest = bundle_set.extract_bundle_set(Path(args.archive), destination)
    restored = [str((destination / entry.name).resolve()) for entry in manifest.cases]
    payload: dict[str, object] = {
        "ok": True,
        "destination": str(destination.resolve()),
        "manifest": bundle_set.manifest_payload(manifest),
        "cases": restored,
        "next": shlex.join(["ofti", "run", "queue", *restored]),
    }
    if args.json:
        emit_json(payload, args)
    else:
        print(f"Bundle set extracted: {destination.resolve()}")
        print(f"Cases verified: {len(restored)}")
        for case in restored:
            print(f"  {case}")
        print(f"Next: {payload['next']}")
    return 0


def _configured_output(output: Path) -> Path:
    cfg = get_config()
    root = cfg.bundle.output_dir or cfg.paths.bundle_output_dir
    if root and not output.is_absolute():
        return Path(root).expanduser() / output
    return output


def _configured_destination(destination: Path) -> Path:
    root = get_config().paths.case_root
    if root and not destination.is_absolute():
        return Path(root).expanduser() / destination
    return destination


__all__ = ["_build_bundle_set_parsers"]
