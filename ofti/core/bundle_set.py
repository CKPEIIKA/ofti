"""Portable collections of independently runnable OFTI case bundles."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import shutil
import tarfile
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from ofti.core import case_bundle

FORMAT = "ofti.bundle-set"
FORMAT_VERSION = 1
MANIFEST_PATH = ".ofti/bundle-set.json"


@dataclass(frozen=True)
class BundleSetCase:
    name: str
    archive: str
    size: int
    sha256: str
    manifest: case_bundle.BundleManifest


@dataclass(frozen=True)
class BundleSetManifest:
    format: str
    version: int
    name: str
    cases: tuple[BundleSetCase, ...]


def read_case_list(path: Path, *, root: Path) -> list[Path]:
    """Read the one-case-per-line format used by simple HPC queue pumps."""
    list_path = path.expanduser().resolve()
    if not list_path.is_file():
        raise ValueError(f"case list not found: {list_path}")
    case_root = root.expanduser().resolve()
    cases: list[Path] = []
    for raw in list_path.read_text(encoding="utf-8", errors="strict").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        candidate = Path(value).expanduser()
        cases.append(candidate.resolve() if candidate.is_absolute() else (case_root / candidate).resolve())
    if not cases:
        raise ValueError(f"case list is empty: {list_path}")
    return cases


def create_bundle_set(
    case_dirs: list[Path],
    output: Path,
    *,
    name: str | None = None,
    mesh: str = "auto",
    time: str = "0",
    extra_warnings: Mapping[Path, Iterable[str]] | None = None,
) -> BundleSetManifest:
    """Create one deterministic archive containing independent case bundles."""
    cases = _resolved_cases(case_dirs)
    warnings_by_case = {
        path.expanduser().resolve(): tuple(warnings) for path, warnings in (extra_warnings or {}).items()
    }
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    set_name = name.strip() if name else _archive_stem(output)
    if not set_name:
        raise ValueError("bundle-set name must not be empty")
    with tempfile.TemporaryDirectory(prefix=".ofti-bundle-set-", dir=output.parent) as raw_stage:
        stage = Path(raw_stage)
        entries = tuple(
            _create_case_entry(
                case,
                stage,
                index=index,
                mesh=mesh,
                time=time,
                extra_warnings=warnings_by_case.get(case, ()),
            )
            for index, case in enumerate(cases)
        )
        manifest = BundleSetManifest(format=FORMAT, version=FORMAT_VERSION, name=set_name, cases=entries)
        temporary = stage / "bundle-set.tar.gz"
        _write_bundle_set(temporary, stage, manifest)
        temporary.replace(output)
    return manifest


def read_bundle_set_manifest(archive: Path) -> BundleSetManifest:
    manifests: list[BundleSetManifest] = []
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            if member.name != MANIFEST_PATH:
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ValueError(f"unsafe bundle-set manifest member: {archive}")
            source = tar.extractfile(member)
            if source is not None:
                manifests.append(manifest_from_payload(json.loads(source.read().decode())))
    if len(manifests) == 1:
        return manifests[0]
    if len(manifests) > 1:
        raise ValueError(f"bundle-set manifest is duplicated: {archive}")
    raise ValueError(f"bundle-set manifest is unreadable: {archive}")


def extract_bundle_set(archive: Path, destination: Path) -> BundleSetManifest:
    """Verify and extract every case bundle under ``destination/<case-name>``."""
    manifest = read_bundle_set_manifest(archive)
    destination = destination.expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"destination is not empty: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ofti-unbundle-set-", dir=destination.parent) as raw_stage:
        stage = Path(raw_stage)
        archives = stage / "archives"
        archives.mkdir()
        _extract_inner_archives(archive, archives, manifest)
        cases_root = stage / "cases"
        cases_root.mkdir()
        for entry in manifest.cases:
            case_bundle.extract_bundle(archives / entry.archive, cases_root / entry.name)
        if destination.exists():
            destination.rmdir()
        cases_root.replace(destination)
    return manifest


def manifest_payload(manifest: BundleSetManifest) -> dict[str, object]:
    payload = asdict(manifest)
    payload["format_version"] = manifest.version
    payload["cases"] = [
        {
            "name": entry.name,
            "archive": entry.archive,
            "size": entry.size,
            "sha256": entry.sha256,
            "manifest": case_bundle.manifest_payload(entry.manifest),
        }
        for entry in manifest.cases
    ]
    return payload


def manifest_from_payload(payload: dict[str, object]) -> BundleSetManifest:
    version = _integer(payload.get("format_version", payload.get("version")))
    if payload.get("format") != FORMAT:
        raise ValueError(f"not an OFTI bundle set: {payload.get('format')}")
    if version != FORMAT_VERSION:
        raise ValueError(f"unsupported bundle-set manifest version: {version}")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("bundle-set manifest contains no cases")
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("bundle-set manifest name is empty")
    entries = tuple(_case_from_payload(item) for item in raw_cases)
    _validate_entry_names(entries)
    return BundleSetManifest(format=FORMAT, version=version, name=name, cases=entries)


def _resolved_cases(case_dirs: list[Path]) -> list[Path]:
    if not case_dirs:
        raise ValueError("bundle set requires at least one case")
    cases = [path.expanduser().resolve() for path in case_dirs]
    missing = [str(path) for path in cases if not path.is_dir()]
    if missing:
        raise ValueError("case does not exist: " + ", ".join(missing))
    if len(set(cases)) != len(cases):
        raise ValueError("bundle set contains duplicate case paths")
    names = [path.name for path in cases]
    if len(set(names)) != len(names):
        raise ValueError("bundle set case directory names must be unique")
    return cases


def _create_case_entry(
    case: Path,
    stage: Path,
    *,
    index: int,
    mesh: str,
    time: str,
    extra_warnings: tuple[str, ...],
) -> BundleSetCase:
    archive = Path("cases") / f"{index:04d}-{_safe_archive_name(case.name)}.ofti.tar.gz"
    target = stage / archive
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = case_bundle.create_bundle(case, target, mesh=mesh, time=time, extra_warnings=extra_warnings)
    return BundleSetCase(
        name=case.name,
        archive=archive.as_posix(),
        size=target.stat().st_size,
        sha256=_sha256(target),
        manifest=manifest,
    )


def _write_bundle_set(output: Path, stage: Path, manifest: BundleSetManifest) -> None:
    with (
        output.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for entry in manifest.cases:
            _add_file(tar, stage / entry.archive, entry.archive)
        data = json.dumps(manifest_payload(manifest), indent=2, sort_keys=True).encode()
        _add_bytes(tar, MANIFEST_PATH, data)


def _extract_inner_archives(archive: Path, destination: Path, manifest: BundleSetManifest) -> None:
    expected = {entry.archive: entry for entry in manifest.cases}
    seen: set[str] = set()
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            if member.name == MANIFEST_PATH:
                continue
            entry = expected.get(member.name)
            if entry is None:
                raise ValueError(f"unexpected bundle-set member: {member.name}")
            if member.name in seen:
                raise ValueError(f"duplicate bundle-set member: {member.name}")
            _write_inner_archive(tar, member, destination / entry.archive, entry)
            seen.add(member.name)
    missing = sorted(set(expected).difference(seen))
    if missing:
        raise ValueError("bundle-set archives are missing: " + ", ".join(missing))


def _write_inner_archive(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    target: Path,
    entry: BundleSetCase,
) -> None:
    if member.issym() or member.islnk() or not member.isfile() or _safe_path(member.name) is None:
        raise ValueError(f"unsafe bundle-set member: {member.name}")
    source = tar.extractfile(member)
    if source is None:
        raise ValueError(f"bundle-set member is unreadable: {member.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)
    if target.stat().st_size != entry.size or _sha256(target) != entry.sha256:
        raise ValueError(f"bundle-set verification failed: {member.name}")


def _case_from_payload(value: object) -> BundleSetCase:
    if not isinstance(value, dict):
        raise TypeError("invalid bundle-set case entry")
    item = cast("dict[str, object]", value)
    raw_manifest = item.get("manifest")
    if not isinstance(raw_manifest, dict):
        raise TypeError("bundle-set case manifest is missing")
    case_manifest = cast("dict[str, object]", raw_manifest)
    entry = BundleSetCase(
        name=str(item.get("name", "")),
        archive=str(item.get("archive", "")),
        size=_integer(item.get("size")),
        sha256=str(item.get("sha256", "")),
        manifest=case_bundle.manifest_from_payload(case_manifest),
    )
    if _safe_path(entry.archive) is None or not entry.archive.startswith("cases/"):
        raise ValueError(f"unsafe bundle-set archive path: {entry.archive}")
    if Path(entry.name).name != entry.name or not entry.name.strip() or entry.name in {".", ".."}:
        raise ValueError(f"unsafe bundle-set case name: {entry.name}")
    if entry.size < 0 or re.fullmatch(r"[0-9a-f]{64}", entry.sha256) is None:
        raise ValueError(f"invalid bundle-set archive metadata: {entry.archive}")
    if entry.manifest.case_name != entry.name:
        raise ValueError(f"bundle-set case name does not match inner manifest: {entry.name}")
    return entry


def _validate_entry_names(entries: tuple[BundleSetCase, ...]) -> None:
    names = [entry.name for entry in entries]
    archives = [entry.archive for entry in entries]
    if len(set(names)) != len(names) or len(set(archives)) != len(archives):
        raise ValueError("bundle-set manifest contains duplicate cases")


def _safe_path(value: str) -> Path | None:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        return None
    return Path(*pure.parts)


def _safe_archive_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "case"


def _archive_stem(path: Path) -> str:
    name = path.name
    for suffix in (".tar.gz", ".tgz"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _add_file(tar: tarfile.TarFile, path: Path, arcname: str) -> None:
    info = tar.gettarinfo(str(path), arcname=arcname)
    _normalize(info)
    with path.open("rb") as handle:
        tar.addfile(info, handle)


def _add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    _normalize(info)
    tar.addfile(info, io.BytesIO(data))


def _normalize(info: tarfile.TarInfo) -> None:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
