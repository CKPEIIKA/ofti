from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ofti.core.checkpoint import checkpoint_health
from ofti.core.times import numeric_time_directories, processor_dirs

FORMAT = "ofti.result-pack"
FORMAT_VERSION = 1
MANIFEST_PATH = ".ofti/result-pack.json"


def create_result_pack(
    case_dir: Path,
    output: Path,
    *,
    time_name: str = "latest",
    include_processors: bool = False,
) -> dict[str, Any]:
    case = case_dir.resolve()
    selected_time = _select_result_time(
        case,
        time_name,
        include_processors=include_processors,
    )
    paths = _result_paths(case, selected_time, include_processors=include_processors)
    files = [_file_record(case, path) for path in paths]
    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "case_name": case.name,
        "selected_time": selected_time,
        "include_processors": include_processors,
        "files": files,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for record in files:
            _add_file(archive, case / record["path"], record["path"])
        _add_bytes(archive, MANIFEST_PATH, json.dumps(manifest, indent=2).encode())
    return manifest


def extract_result_pack(archive_path: Path, destination: Path) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:*") as archive:
        manifest = _read_manifest(archive)
        expected = {str(row["path"]): row for row in manifest["files"]}
        members = {member.name: member for member in archive.getmembers()}
        for rel_path, record in expected.items():
            member = members.get(rel_path)
            if member is None or not member.isfile():
                raise ValueError(f"result pack member missing: {rel_path}")
            target = _safe_target(destination, rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"result pack member unreadable: {rel_path}")
            data = source.read()
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError(f"result pack hash mismatch: {rel_path}")
            target.write_bytes(data)
    return manifest


def _select_result_time(case: Path, time_name: str, *, include_processors: bool) -> str:
    root_times = [path.name for path in numeric_time_directories(case) if _has_files(path)]
    if time_name != "latest":
        if time_name in root_times:
            return time_name
        if include_processors and time_name in checkpoint_health(case)["complete_times"]:
            return time_name
        raise ValueError(f"complete result time not found: {time_name}")
    if root_times:
        return root_times[-1]
    if include_processors and processor_dirs(case):
        latest = checkpoint_health(case)["latest_complete_time"]
        if isinstance(latest, str):
            return latest
    raise ValueError("no reconstructed result time is available to pack")


def _result_paths(case: Path, time_name: str, *, include_processors: bool) -> list[Path]:
    roots = [case / time_name, case / "postProcessing", case / "runs"]
    paths = [path for root in roots if root.exists() for path in _files(root)]
    paths.extend(path for path in case.glob("log.*") if path.is_file())
    if include_processors:
        health = checkpoint_health(case)
        if time_name not in health["complete_times"]:
            raise ValueError(
                f"processor state at {time_name} is not complete across every processor",
            )
        for processor in processor_dirs(case):
            paths.extend(_files(processor / time_name))
            paths.extend(_files(processor / "constant" / "polyMesh"))
    return sorted(set(paths), key=lambda path: path.relative_to(case).as_posix())


def _files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    paths = sorted(path for path in root.rglob("*") if path.is_file())
    if any(path.is_symlink() for path in paths):
        raise ValueError(f"result pack does not allow symlinks under {root}")
    return paths


def _file_record(case: Path, path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"result pack does not allow symlinks: {path}")
    data = path.read_bytes()
    return {
        "path": path.relative_to(case).as_posix(),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _read_manifest(archive: tarfile.TarFile) -> dict[str, Any]:
    member = archive.getmember(MANIFEST_PATH)
    source = archive.extractfile(member)
    if source is None:
        raise ValueError("result pack manifest is unreadable")
    payload = json.loads(source.read())
    if payload.get("format") != FORMAT or payload.get("format_version") != FORMAT_VERSION:
        raise ValueError("unsupported result pack format")
    if not isinstance(payload.get("files"), list):
        raise TypeError("result pack manifest has no file list")
    return payload


def _safe_target(destination: Path, rel_path: str) -> Path:
    pure = PurePosixPath(rel_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe result pack path: {rel_path}")
    return destination.joinpath(*pure.parts)


def _add_file(archive: tarfile.TarFile, path: Path, arcname: str) -> None:
    info = archive.gettarinfo(str(path), arcname=arcname)
    _normalize(info)
    with path.open("rb") as source:
        archive.addfile(info, source)


def _add_bytes(archive: tarfile.TarFile, arcname: str, data: bytes) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    _normalize(info)
    archive.addfile(info, io.BytesIO(data))


def _normalize(info: tarfile.TarInfo) -> None:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.mode = 0o644


def _has_files(path: Path) -> bool:
    return any(candidate.is_file() for candidate in path.rglob("*"))
