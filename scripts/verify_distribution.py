#!/usr/bin/env python3
"""Verify OFTI wheel and source-distribution metadata."""

from __future__ import annotations

import email
import sys
import tarfile
import zipfile
from pathlib import Path

from ofti import __version__

LICENSE_EXPRESSION = "GPL-3.0-or-later"


def _wheel_metadata(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected one wheel METADATA file")
        return archive.read(names[0]).decode()


def _sdist_metadata(path: Path) -> str:
    with tarfile.open(path, "r:gz") as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.name.count("/") == 1 and member.name.endswith("/PKG-INFO")
        ]
        if len(members) != 1:
            raise ValueError(f"{path}: expected one source PKG-INFO file")
        stream = archive.extractfile(members[0])
        if stream is None:
            raise ValueError(f"{path}: could not read source PKG-INFO")
        return stream.read().decode()


def _verify_metadata(path: Path, text: str) -> None:
    metadata = email.message_from_string(text)
    if metadata["Version"] != __version__:
        raise ValueError(f"{path}: version {metadata['Version']!r} != {__version__!r}")
    if metadata["License-Expression"] != LICENSE_EXPRESSION:
        raise ValueError(
            f"{path}: license {metadata['License-Expression']!r} != {LICENSE_EXPRESSION!r}",
        )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0] if args else "dist")
    wheels = sorted(root.glob("ofti-*.whl"))
    sdists = sorted(root.glob("ofti-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print(f"expected one OFTI wheel and one source archive under {root}", file=sys.stderr)
        return 2
    try:
        _verify_metadata(wheels[0], _wheel_metadata(wheels[0]))
        _verify_metadata(sdists[0], _sdist_metadata(sdists[0]))
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"distribution verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified OFTI {__version__} ({LICENSE_EXPRESSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
