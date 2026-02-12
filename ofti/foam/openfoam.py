from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ofti.foamlib import adapter as foamlib_integration


class OpenFOAMError(RuntimeError):
    @classmethod
    def missing_openfoam_tools(cls) -> OpenFOAMError:
        return cls(
            "OpenFOAM tools not found on PATH. "
            "Please source your OpenFOAM bashrc before running ofti.",
        )

    @classmethod
    def foamlib_keywords_failed(cls, exc: Exception) -> OpenFOAMError:
        return cls(f"foamlib failed to parse keywords: {exc}")

    @classmethod
    def foamlib_entry_failed(cls, exc: Exception) -> OpenFOAMError:
        return cls(f"foamlib failed to parse entry: {exc}")

def _foamlib_candidate(file_path: Path) -> bool:
    try:
        head = file_path.read_text(errors="ignore")[:2048]
    except OSError:
        return False
    return "FoamFile" in head


def list_keywords(file_path: Path) -> list[str]:
    """
    List top-level keywords for a dictionary file.
    """
    if _foamlib_candidate(file_path):
        try:
            return foamlib_integration.list_keywords(file_path)
        except Exception as exc:
            logging.debug("foamlib list_keywords failed: %s", exc)
    raise OpenFOAMError("Failed to list keywords.")


def list_subkeys(file_path: Path, entry: str) -> list[str]:
    """
    List sub-keys for a dictionary entry, if it is itself a dictionary.
    """
    if _foamlib_candidate(file_path):
        try:
            return foamlib_integration.list_subkeys(file_path, entry)
        except Exception as exc:
            logging.debug("foamlib list_subkeys failed: %s", exc)
        return []
    return []


def get_entry_comments(file_path: Path, key: str) -> list[str]:
    """
    Try to extract comment lines associated with an entry from the file.

    This is a heuristic: it searches for the first line containing the
    key and then collects immediately preceding comment lines starting
    with '//' or '/*' or '*'.
    """
    comments: list[str] = []
    try:
        text = file_path.read_text()
    except OSError:
        return comments

    lines = text.splitlines()
    key_lower = key.rsplit(".", maxsplit=1)[-1].lower()

    for i, line in enumerate(lines):
        if key_lower in line.lower():
            # Walk backwards collecting consecutive comment lines.
            j = i - 1
            while j >= 0:
                stripped = lines[j].lstrip()
                if stripped.startswith(("//", "/*", "*")):
                    comments.insert(0, stripped)
                    j -= 1
                else:
                    break
            break

    return comments


def get_entry_info(file_path: Path, key: str) -> list[str]:
    """
    Try to obtain additional information about an entry using foamlib.

    Returns the output lines (if any), or an empty list when the
    command is not available or fails.
    """
    return []


def get_entry_enum_values(file_path: Path, key: str) -> list[str]:
    """
    Try to obtain a set of allowed values for an entry.

    Returns the values (if any), or an empty list when the command
    fails or no values are reported.
    """
    return []


def parse_required_entries(info_lines: Sequence[str]) -> list[str]:
    """
    Parse required entry hints from foamlib info output.

    Several OpenFOAM dictionaries emit lines such as

    ``Required entries: type value``

    or bullet lists. This helper extracts the reported entry names
    so that callers can verify they exist on disk.
    """

    required: list[str] = []
    capture_block = False

    for raw in info_lines:
        line = raw.strip()
        lower = line.lower()

        if not line:
            capture_block = False
            continue

        if lower.startswith("optional"):
            # Explicitly skip optional hints when we are collecting a block.
            continue

        if lower.startswith(("required entries", "required entry")):
            capture_block = True
            after_colon = line.split(":", 1)[1] if ":" in line else ""
            if after_colon.strip():
                required.extend(_split_requirement_line(after_colon))
                capture_block = False
            continue

        if capture_block:
            if ":" in line and not lower.startswith("required"):
                capture_block = False
                continue
            required.extend(_split_requirement_line(line))

    # Deduplicate while keeping order.
    seen: set[str] = set()
    unique: list[str] = []
    for item in required:
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _split_requirement_line(text: str) -> list[str]:
    cleaned = text.strip("-: ")
    if not cleaned:
        return []
    tokens = re.split(r"[,\s]+", cleaned)
    return [tok for tok in tokens if tok and tok.lower() not in {"entries", "entry"}]


def missing_required_entries(required: Sequence[str], available: Sequence[str]) -> list[str]:
    available_set = set(available)
    return [req for req in required if req not in available_set]


def normalize_scalar_token(value: str) -> str:
    """
    Extract the final scalar token from an entry for comparison against enums.

    Enum lists often report plain tokens without trailing semicolons.
    This helper mirrors the heuristic used by the editor for determining
    scalar types so that enum validation is consistent across the TUI and
    automated checks.
    """

    if not value:
        return ""
    cleaned = value.replace(";", " ").strip()
    if not cleaned:
        return ""
    token = cleaned.split()[-1]
    return token.strip('"')


def is_scalar_value(value: str) -> bool:
    """
    Return True if the value looks like a single scalar token.
    """
    if not value:
        return False
    cleaned = value.replace(";", " ").strip()
    if not cleaned:
        return False
    if any(ch in cleaned for ch in "{}[]()"):
        return False
    return len(cleaned.split()) == 1


def looks_like_dict(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return False
    return cleaned.startswith("{") or "{\n" in cleaned or "{" in cleaned


def read_entry(file_path: Path, key: str) -> str:
    if _foamlib_candidate(file_path):
        try:
            return foamlib_integration.read_entry(file_path, key)
        except KeyError as exc:
            raise OpenFOAMError(str(exc)) from exc
        except Exception as exc:
            logging.debug("foamlib read_entry failed: %s", exc)
    raise OpenFOAMError(f"Failed to read entry {key}.")


def write_entry(file_path: Path, key: str, value: str) -> bool:
    if _foamlib_candidate(file_path):
        try:
            return foamlib_integration.write_entry(file_path, key, value)
        except Exception as exc:
            logging.debug("foamlib write_entry failed: %s", exc)
    return False


def discover_case_files(case_dir: Path) -> dict[str, list[Path]]:  # noqa: C901
    """
    Discover candidate dictionary files in an OpenFOAM case.

    Returns a mapping: section -> list of files.
    Sections: "system", "constant", "0*".
    """
    case_dir = case_dir.resolve()
    sections = {"system": [], "constant": [], "0*": []}  # type: Dict[str, List[Path]]

    system_dir = case_dir / "system"
    if system_dir.is_dir():
        sections["system"] = sorted(p for p in system_dir.iterdir() if p.is_file())

    constant_dir = case_dir / "constant"
    if constant_dir.is_dir():
        sections["constant"] = sorted(p for p in constant_dir.iterdir() if p.is_file())

    zero_dirs: list[Path] = []
    for entry in case_dir.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if not name.startswith("0"):
            continue
        include = True
        try:
            value = float(name)
        except ValueError:
            include = True
        else:
            include = value == 0.0
        if include:
            zero_dirs.append(entry)

    zero_files: list[Path] = []
    for d in zero_dirs:
        zero_files.extend(p for p in d.iterdir() if p.is_file())
    sections["0*"] = sorted(zero_files)

    if os.environ.get("OFTI_STRICT_FOAMLIB") == "1":
        sections = _filter_foamlib_files(sections)

    return sections


def _filter_foamlib_files(sections: dict[str, list[Path]]) -> dict[str, list[Path]]:
    filtered: dict[str, list[Path]] = {}
    for key, files in sections.items():
        filtered[key] = [path for path in files if foamlib_integration.is_foam_file(path)]
    return filtered


@dataclass
class FileCheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: bool = False


def verify_case(
    case_dir: Path,
    progress: Callable[[Path], None] | None = None,
    result_callback: Callable[[Path, FileCheckResult], None] | None = None,
) -> dict[Path, FileCheckResult]:
    """
    Run a correctness check over all discovered dictionary files.

    Beyond ensuring the files parse, this inspects each entry recursively
    to detect missing required sub-entries and invalid enum values.
    """

    all_files = _collect_case_files(case_dir)
    results = {file_path: FileCheckResult() for file_path in all_files}

    for file_path in all_files:
        if progress:
            progress(file_path)
        result = results[file_path]
        if not _check_file(file_path, result, result_callback):
            break

    return results


def _collect_case_files(case_dir: Path) -> list[Path]:
    sections = discover_case_files(case_dir)
    all_files: list[Path] = []
    for files in sections.values():
        all_files.extend(files)
    return all_files


def _check_file(
    file_path: Path,
    result: FileCheckResult,
    result_callback: Callable[[Path, FileCheckResult], None] | None,
) -> bool:
    try:
        top_level_keys = list_keywords(file_path)
    except OpenFOAMError as exc:
        msg = str(exc).strip() or "Unknown error"
        result.errors.append(msg)
        result.checked = True
        if result_callback:
            result_callback(file_path, result)
        return True
    except KeyboardInterrupt:
        return False

    if _foamlib_candidate(file_path):
        result.warnings.extend(_foamlib_quick_lint(file_path, top_level_keys))

    try:
        _check_entries(file_path, result, top_level_keys)
        _check_boundary_field(file_path, result, top_level_keys)
    except KeyboardInterrupt:
        return False

    result.checked = True
    if result_callback:
        result_callback(file_path, result)
    return True


def _check_boundary_field(
    file_path: Path,
    result: FileCheckResult,
    top_level_keys: Sequence[str],
) -> None:
    if "boundaryField" not in top_level_keys:
        return
    patches = list_subkeys(file_path, "boundaryField")
    nested_keys = [f"boundaryField.{patch}" for patch in patches]
    _check_entries(file_path, result, nested_keys)
    _check_boundary_patches(file_path, result, patches)


def _check_entries(file_path: Path, result: FileCheckResult, keys: Sequence[str]) -> None:
    for key in keys:
        _check_single_entry(file_path, result, key)


def _check_single_entry(file_path: Path, result: FileCheckResult, key: str) -> None:
    required_issues = _required_entries_issues(file_path, key)
    if required_issues:
        result.errors.extend(required_issues)
    value: str | None = None

    enum_values = get_entry_enum_values(file_path, key)
    if enum_values:
        if value is None:
            try:
                value = read_entry(file_path, key)
            except OpenFOAMError as exc:
                result.errors.append(f"{key}: {exc}")
                return
        if looks_like_dict(value):
            return
        token = normalize_scalar_token(value)
        if not token:
            return
        allowed = {val.strip() for val in enum_values if val.strip()}
        if token and token not in allowed:
            allowed_list = ", ".join(sorted(allowed))
            result.errors.append(
                f"{key}: invalid value '{token}'. Allowed: {allowed_list}",
            )


def _required_entries_issues(file_path: Path, key: str) -> list[str]:
    info_lines = get_entry_info(file_path, key)
    required = parse_required_entries(info_lines)
    if not required:
        return []
    subkeys = list_subkeys(file_path, key)
    if subkeys:
        missing = missing_required_entries(required, subkeys)
        if missing:
            return [f"{key}: missing required entries: {', '.join(missing)}"]
        return []
    try:
        value = read_entry(file_path, key)
    except OpenFOAMError:
        return []
    if value and looks_like_dict(value):
        missing = missing_required_entries(required, [])
        if missing:
            return [f"{key}: missing required entries: {', '.join(missing)}"]
    return []


def _find_case_root(file_path: Path) -> Path | None:
    for parent in file_path.resolve().parents:
        boundary_path = parent / "constant" / "polyMesh" / "boundary"
        if boundary_path.exists():
            return parent
    return None


def _check_boundary_patches(
    file_path: Path,
    result: FileCheckResult,
    boundary_keys: Sequence[str],
) -> None:
    case_root = _find_case_root(file_path)
    if case_root is None:
        return
    boundary_file = case_root / "constant" / "polyMesh" / "boundary"
    if not boundary_file.exists():
        return
    try:
        patches, patch_types = foamlib_integration.parse_boundary_file(boundary_file)
    except Exception:
        return
    if not patches:
        return
    if ".*" in boundary_keys:
        return
    mesh_patches = [
        patch
        for patch in patches
        if not patch.startswith("processor") and patch_types.get(patch) != "processor"
    ]
    if not mesh_patches:
        return
    missing = [patch for patch in mesh_patches if patch not in boundary_keys]
    if missing:
        missing_list = ", ".join(missing)
        result.errors.append(f"boundaryField missing patches: {missing_list}")


def _foamlib_quick_lint(file_path: Path, keys: Sequence[str]) -> list[str]:
    warnings: list[str] = []
    parts = file_path.parts
    if ("0" in parts or "0.orig" in parts) and "boundaryField" not in keys:
        warnings.append("boundaryField missing.")
    name = file_path.name
    if name == "controlDict" and "application" not in keys:
        warnings.append("controlDict missing 'application'.")
    if name == "fvSolution" and "solvers" not in keys:
        warnings.append("fvSolution missing 'solvers'.")
    if name == "fvSchemes" and "ddtSchemes" not in keys:
        warnings.append("fvSchemes missing 'ddtSchemes'.")
    return warnings
