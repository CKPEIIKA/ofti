"""Portable OpenFOAM case bundle helpers.

The bundle layer is filesystem-only: it selects a minimal case tree, writes a
small manifest, and archives it. Running or smoking an unpacked case stays in
CLI/tool services.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib
import io
import json
import re
import tarfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Literal, cast

from ofti.core.case_headers import detect_case_header_version
from ofti.core.syntax import find_suspicious_lines
from ofti.core.times import latest_time

MeshPolicy = Literal["auto", "include", "exclude"]
ArchiveFormat = Literal["gztar", "zstdtar"]
MANIFEST_PATH = ".ofti/bundle.json"
MANIFEST_FORMAT = "ofti.case-bundle"
MANIFEST_FORMAT_VERSION = 1

_EXCLUDED_DIRS = {"postProcessing", "dynamicCode", ".git", "__pycache__"}
_EXCLUDED_FILE_PREFIXES = ("log.",)
_INCLUDED_ROOT_FILES = {"Allrun", "Allclean"}
_LOCAL_INCLUDE_RE = re.compile(r'^\s*#\s*include(?:IfPresent)?\s+"(?P<path>[^"]+)"')


@dataclass(frozen=True)
class BundleFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class BundleManifest:
    format: str
    version: int
    case_name: str
    start_time: str
    mesh_policy: MeshPolicy
    application: str
    header_version: str
    files: tuple[BundleFile, ...]
    warnings: tuple[str, ...] = ()


def build_bundle_manifest(
    case_dir: Path,
    *,
    mesh: MeshPolicy = "auto",
    time: str = "0",
    extra_warnings: Iterable[str] = (),
) -> BundleManifest:
    """Return the deterministic manifest for files selected from ``case_dir``."""
    root = case_dir.resolve()
    selected_time = _selected_time(root, time)
    selected_files = select_bundle_files(root, mesh=mesh, time=selected_time)
    warnings = _validate_bundle_case(root, selected_time, mesh=mesh)
    warnings += _include_warnings(root, selected_files)
    warnings += _syntax_warnings(root, selected_files)
    warnings += tuple(extra_warnings)
    application = _control_application(root)
    files = tuple(_file_entry(root, rel) for rel in selected_files)
    return BundleManifest(
        format=MANIFEST_FORMAT,
        version=MANIFEST_FORMAT_VERSION,
        case_name=root.name,
        start_time=selected_time,
        mesh_policy=mesh,
        application=application,
        header_version=detect_case_header_version(root),
        files=files,
        warnings=warnings,
    )


def select_bundle_files(
    case_dir: Path,
    *,
    mesh: MeshPolicy = "auto",
    time: str = "0",
) -> list[Path]:
    """Select relative case files for a portable minimal archive."""
    root = case_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"case does not exist: {case_dir}")
    rels: set[Path] = set()
    for dirname in ("system", "constant", time):
        _add_tree(rels, root, Path(dirname), mesh=mesh)
    _add_root_files(rels, root)
    _add_ofti_metadata(rels, root)
    _add_mesh_tree(rels, root, mesh)
    _add_referenced_include_files(rels, root, mesh=mesh)
    return sorted(rels, key=lambda rel: rel.as_posix())


def create_bundle(
    case_dir: Path,
    output: Path,
    *,
    mesh: MeshPolicy = "auto",
    time: str = "0",
    extra_warnings: Iterable[str] = (),
) -> BundleManifest:
    """Create a deterministic tar archive and return its manifest."""
    manifest = build_bundle_manifest(case_dir, mesh=mesh, time=time, extra_warnings=extra_warnings)
    output.parent.mkdir(parents=True, exist_ok=True)
    root = case_dir.resolve()
    with _deterministic_bundle_tar(output) as tar:
        _write_bundle_tar(tar, root, manifest)
    return manifest


def read_bundle_manifest(archive: Path) -> BundleManifest:
    with _open_bundle_tar_for_read(archive) as tar:
        for member in tar:
            if member.name != MANIFEST_PATH:
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                break
            payload = json.loads(extracted.read().decode())
            return manifest_from_payload(payload)
    raise ValueError(f"bundle manifest is unreadable: {archive}")


def extract_bundle(archive: Path, destination: Path, *, force: bool = False) -> BundleManifest:
    """Extract a bundle, verify hashes, and return the embedded manifest."""
    manifest = read_bundle_manifest(archive)
    if destination.exists() and any(destination.iterdir()) and not force:
        raise ValueError(f"destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    with _open_bundle_tar_for_read(archive) as tar:
        for member in tar:
            if member.isdir():
                continue
            rel = _safe_member_path(member.name)
            if rel is None or rel.as_posix() == MANIFEST_PATH:
                continue
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            target.write_bytes(source.read())
            target.chmod(member.mode & 0o777)
    verify_bundle_files(destination, manifest)
    return manifest


def verify_bundle_files(case_dir: Path, manifest: BundleManifest) -> list[str]:
    errors: list[str] = []
    for entry in manifest.files:
        path = case_dir / entry.path
        if not path.is_file():
            errors.append(f"missing: {entry.path}")
            continue
        if path.stat().st_size != entry.size:
            errors.append(f"size mismatch: {entry.path}")
        digest = _sha256(path)
        if digest != entry.sha256:
            errors.append(f"hash mismatch: {entry.path}")
    if errors:
        raise ValueError("bundle verification failed: " + "; ".join(errors))
    return errors


def manifest_payload(manifest: BundleManifest) -> dict[str, object]:
    payload = asdict(manifest)
    payload["format_version"] = manifest.version
    payload["files"] = [asdict(entry) for entry in manifest.files]
    return payload


def environment_requirements(manifest: BundleManifest) -> dict[str, object]:
    """Return the target-host requirements implied by a bundle manifest."""
    mesh_included = any(entry.path.startswith("constant/polyMesh/") for entry in manifest.files)
    notes: list[str] = []
    if manifest.header_version == "unknown":
        notes.append("OpenFOAM header version was not detected; verify target OpenFOAM manually")
    else:
        notes.append(f"OpenFOAM-compatible case header: {manifest.header_version}")
    if mesh_included:
        notes.append("Mesh is included in constant/polyMesh")
    else:
        notes.append("Mesh is not included; generate or reconstruct mesh on the target host")
    return {
        "solver": manifest.application,
        "openfoam_header": manifest.header_version,
        "start_time": manifest.start_time,
        "mesh_policy": manifest.mesh_policy,
        "mesh_included": mesh_included,
        "run_command": f"ofti run solver CASE --solver {manifest.application}",
        "notes": notes,
    }


def manifest_from_payload(payload: dict[str, object]) -> BundleManifest:
    files = tuple(
        BundleFile(**entry)
        for entry in _payload_files(payload.get("files"))
        if isinstance(entry, dict)
    )
    return BundleManifest(
        format=str(payload.get("format", "")),
        version=_payload_int(payload.get("format_version", payload.get("version")), default=0),
        case_name=str(payload.get("case_name", "")),
        start_time=str(payload.get("start_time", "0")),
        mesh_policy=_mesh_policy(str(payload.get("mesh_policy", "auto"))),
        application=str(payload.get("application", "")),
        header_version=str(payload.get("header_version", "unknown")),
        files=files,
        warnings=_payload_strings(payload.get("warnings")),
    )


@contextmanager
def _deterministic_bundle_tar(output: Path) -> Iterator[tarfile.TarFile]:
    if _is_zstd_archive(output):
        with _deterministic_zstd_tar(output) as tar:
            yield tar
        return
    with _deterministic_gzip_tar(output) as tar:
        yield tar


@contextmanager
def _deterministic_gzip_tar(output: Path) -> Iterator[tarfile.TarFile]:
    with (
        output.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gzip_file,
        tarfile.open(fileobj=gzip_file, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        yield tar


@contextmanager
def _deterministic_zstd_tar(output: Path) -> Iterator[tarfile.TarFile]:
    zstandard = _zstandard_module()
    compressor = zstandard.ZstdCompressor(
        level=3,
        write_content_size=False,
        write_checksum=True,
        write_dict_id=False,
    )
    with (
        output.open("wb") as raw,
        compressor.stream_writer(raw, closefd=False) as compressed,
        tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar,
    ):
        yield tar


@contextmanager
def _open_bundle_tar_for_read(archive: Path) -> Iterator[tarfile.TarFile]:
    if _is_zstd_archive(archive):
        zstandard = _zstandard_module()
        decompressor = zstandard.ZstdDecompressor()
        with (
            archive.open("rb") as raw,
            decompressor.stream_reader(raw, closefd=False) as decompressed,
            tarfile.open(fileobj=decompressed, mode="r|") as tar,
        ):
            yield tar
        return
    with tarfile.open(archive, "r:*") as tar:
        yield tar


def _is_zstd_archive(path: Path) -> bool:
    return path.name.endswith((".tar.zst", ".tzst"))


def _zstandard_module() -> ModuleType:
    try:
        return importlib.import_module("zstandard")
    except ImportError as exc:
        raise ValueError(
            ".tar.zst bundle support requires the optional 'zstandard' package; "
            "use .tar.gz or install zstandard",
        ) from exc


def _write_bundle_tar(tar: tarfile.TarFile, root: Path, manifest: BundleManifest) -> None:
    for entry in manifest.files:
        _add_tar_file(tar, root / entry.path, entry.path)
    payload = json.dumps(manifest_payload(manifest), indent=2, sort_keys=True).encode()
    _add_tar_bytes(tar, MANIFEST_PATH, payload)


def _selected_time(case_dir: Path, time: str) -> str:
    return latest_time(case_dir) if time == "latest" else time


def _payload_files(value: object) -> Iterable[Any]:
    return value if isinstance(value, list) else []


def _payload_int(value: object, *, default: int) -> int:
    if isinstance(value, int | str):
        return int(value)
    return default


def _payload_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _validate_bundle_case(case_dir: Path, time: str, *, mesh: MeshPolicy) -> tuple[str, ...]:
    missing = _missing_required_paths(case_dir, time)
    if missing:
        raise ValueError("case is not bundle-ready; missing: " + ", ".join(missing))
    if not _control_application(case_dir):
        raise ValueError("case is not bundle-ready; system/controlDict has no application entry")
    warnings: list[str] = []
    if mesh == "exclude":
        warnings.append(
            "mesh excluded; target host must reconstruct or generate mesh before solver run",
        )
    elif not (case_dir / "constant" / "polyMesh").is_dir():
        warnings.append(
            "constant/polyMesh not found; direct unbundle --run may need mesh generation first",
        )
    return tuple(warnings)


def _control_application(case_dir: Path) -> str:
    control = case_dir / "system" / "controlDict"
    try:
        text = control.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    match = re.search(r"(?m)^\s*application\s+(?P<value>[^;\s]+)", text)
    return match.group("value").strip() if match else ""


def _include_warnings(case_dir: Path, rels: list[Path]) -> tuple[str, ...]:
    missing = sorted(_missing_include_refs(case_dir, rels))
    return tuple(f"referenced include not bundled: {path}" for path in missing)


def _syntax_warnings(case_dir: Path, rels: list[Path]) -> tuple[str, ...]:
    warnings: list[str] = []
    for rel in rels:
        if not _should_lint_bundle_file(rel):
            continue
        warnings.extend(_file_syntax_warnings(case_dir, rel))
        if len(warnings) >= 20:
            return (*warnings[:20], "syntax warning limit reached")
    return tuple(warnings)


def _file_syntax_warnings(case_dir: Path, rel: Path) -> list[str]:
    path = case_dir / rel
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return [
        f"syntax warning in {rel.as_posix()}: {warning}"
        for warning in find_suspicious_lines(text)
    ]


def _should_lint_bundle_file(rel: Path) -> bool:
    parts = rel.parts
    if len(parts) >= 2 and parts[:2] == ("constant", "polyMesh"):
        return False
    return bool(parts and parts[0] in {"system", "constant", "0", "0.orig"})


def _missing_required_paths(case_dir: Path, time: str) -> list[str]:
    required = [Path("system") / "controlDict", Path("constant"), Path(time)]
    return [path.as_posix() for path in required if not (case_dir / path).exists()]


def _mesh_policy(value: str) -> MeshPolicy:
    if value in {"auto", "include", "exclude"}:
        return cast(MeshPolicy, value)
    return "auto"


def _add_root_files(rels: set[Path], root: Path) -> None:
    for name in _INCLUDED_ROOT_FILES:
        candidate = root / name
        if candidate.is_file():
            rels.add(Path(name))


def _add_ofti_metadata(rels: set[Path], root: Path) -> None:
    for candidate in sorted(root.glob("ofti.*")):
        if candidate.is_file():
            rels.add(candidate.relative_to(root))


def _add_mesh_tree(rels: set[Path], root: Path, mesh: MeshPolicy) -> None:
    poly_mesh = Path("constant") / "polyMesh"
    if mesh == "include" or (mesh == "auto" and (root / poly_mesh).is_dir()):
        _add_tree(rels, root, poly_mesh, mesh="include")


def _add_referenced_include_files(rels: set[Path], root: Path, *, mesh: MeshPolicy) -> None:
    seen: set[Path] = set()
    while pending := sorted(rels - seen, key=lambda rel: rel.as_posix()):
        rel = pending[0]
        seen.add(rel)
        for include in _existing_include_refs(root, rel):
            if _include_file(include, mesh=mesh):
                rels.add(include)


def _existing_include_refs(root: Path, rel: Path) -> list[Path]:
    return [
        include
        for include in _local_include_refs(root, rel)
        if include is not None and (root / include).is_file()
    ]


def _missing_include_refs(root: Path, rels: list[Path]) -> set[str]:
    missing: set[str] = set()
    for rel in rels:
        for text, include in _local_include_ref_items(root, rel):
            if include is None or not (root / include).is_file():
                missing.add(f"{rel.as_posix()} -> {text}")
    return missing


def _local_include_refs(root: Path, rel: Path) -> list[Path | None]:
    return [include for _text, include in _local_include_ref_items(root, rel)]


def _local_include_ref_items(root: Path, rel: Path) -> list[tuple[str, Path | None]]:
    path = root / rel
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    return [
        (match.group("path"), _resolve_case_include(root, rel, match.group("path")))
        for line in lines
        if (match := _LOCAL_INCLUDE_RE.match(line))
    ]


def _resolve_case_include(root: Path, source_rel: Path, include: str) -> Path | None:
    raw = Path(include)
    candidate = raw if raw.is_absolute() else source_rel.parent / raw
    try:
        resolved = (root / candidate).resolve()
        return resolved.relative_to(root.resolve())
    except ValueError:
        return None


def _add_tree(rels: set[Path], root: Path, rel_root: Path, *, mesh: MeshPolicy) -> None:
    base = root / rel_root
    if not base.exists():
        return
    if base.is_file():
        if _include_file(rel_root, mesh=mesh):
            rels.add(rel_root)
        return
    for path in base.rglob("*"):
        rel = path.relative_to(root)
        if path.is_dir() or not _include_file(rel, mesh=mesh):
            continue
        rels.add(rel)


def _include_file(rel: Path, *, mesh: MeshPolicy) -> bool:
    parts = rel.parts
    if any(part.startswith("processor") for part in parts):
        return False
    if any(part in _EXCLUDED_DIRS for part in parts):
        return False
    if mesh == "exclude" and len(parts) >= 2 and parts[:2] == ("constant", "polyMesh"):
        return False
    return not rel.name.startswith(_EXCLUDED_FILE_PREFIXES)


def _file_entry(root: Path, rel: Path) -> BundleFile:
    path = root / rel
    return BundleFile(path=rel.as_posix(), size=path.stat().st_size, sha256=_sha256(path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _add_tar_file(tar: tarfile.TarFile, path: Path, arcname: str) -> None:
    info = tar.gettarinfo(str(path), arcname=arcname)
    _normalize_tar_info(info)
    with path.open("rb") as handle:
        tar.addfile(info, handle)


def _add_tar_bytes(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    _normalize_tar_info(info)
    tar.addfile(info, io.BytesIO(data))


def _normalize_tar_info(info: tarfile.TarInfo) -> None:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0


def _safe_member_path(name: str) -> Path | None:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        return None
    return Path(*pure.parts)
