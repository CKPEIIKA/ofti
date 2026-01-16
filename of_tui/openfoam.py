from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Optional


class OpenFOAMError(RuntimeError):
    pass


def ensure_environment() -> None:
    """
    Ensure OpenFOAM utilities are available.

    This checks for `foamDictionary` on PATH and raises a clear
    error if it is missing. The caller can catch this and show
    a user-friendly message in the TUI.
    """
    if shutil.which("foamDictionary") is None:
        raise OpenFOAMError(
            "foamDictionary not found on PATH. "
            "Please source your OpenFOAM bashrc before running of_tui."
        )


def run_foam_dictionary(
    file_path: Path, args: Iterable[str]
) -> subprocess.CompletedProcess[str]:
    cmd = ["foamDictionary", str(file_path), *args]
    logging.debug("Running command: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise OpenFOAMError(f"Failed to run foamDictionary: {exc}") from exc
    if result.returncode != 0:
        logging.debug("Command failed with code %s: %s", result.returncode, result.stderr.strip())
    return result


def list_keywords(file_path: Path) -> List[str]:
    """
    List top-level keywords for a dictionary file.
    """
    result = run_foam_dictionary(file_path, ["-keywords"])
    if result.returncode != 0:
        raise OpenFOAMError(result.stderr.strip() or "Failed to list keywords.")
    return [line for line in result.stdout.splitlines() if line.strip()]


def list_subkeys(file_path: Path, entry: str) -> List[str]:
    """
    List sub-keys for a dictionary entry, if it is itself a dictionary.
    """
    result = run_foam_dictionary(file_path, ["-entry", entry, "-keywords"])
    if result.returncode != 0:
        # Treat non-dictionary (or missing) entries as having no subkeys.
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def get_entry_comments(file_path: Path, key: str) -> List[str]:
    """
    Try to extract comment lines associated with an entry from the file.

    This is a heuristic: it searches for the first line containing the
    key and then collects immediately preceding comment lines starting
    with '//' or '/*' or '*'.
    """
    comments: List[str] = []
    try:
        text = file_path.read_text()
    except OSError:
        return comments

    lines = text.splitlines()
    key_lower = key.split(".")[-1].lower()

    for i, line in enumerate(lines):
        if key_lower in line.lower():
            # Walk backwards collecting consecutive comment lines.
            j = i - 1
            while j >= 0:
                stripped = lines[j].lstrip()
                if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
                    comments.insert(0, stripped)
                    j -= 1
                else:
                    break
            break

    return comments


def get_entry_info(file_path: Path, key: str) -> List[str]:
    """
    Try to obtain additional information about an entry using
    `foamDictionary -entry <key> -info`.

    Returns the output lines (if any), or an empty list when the
    command is not available or fails.
    """
    result = run_foam_dictionary(file_path, ["-entry", key, "-info"])
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def get_entry_enum_values(file_path: Path, key: str) -> List[str]:
    """
    Try to obtain a set of allowed values for an entry using
    `foamDictionary -entry <key> -list`.

    Returns the values (if any), or an empty list when the command
    fails or no values are reported.
    """
    result = run_foam_dictionary(file_path, ["-entry", key, "-list"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def parse_required_entries(info_lines: Sequence[str]) -> List[str]:
    """
    Parse `foamDictionary -info` output looking for required entry hints.

    Several OpenFOAM dictionaries emit lines such as

    ``Required entries: type value``

    or bullet lists. This helper extracts the reported entry names
    so that callers can verify they exist on disk.
    """

    required: List[str] = []
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

        if lower.startswith("required entries") or lower.startswith("required entry"):
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
    unique: List[str] = []
    for item in required:
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _split_requirement_line(text: str) -> List[str]:
    cleaned = text.strip("-: ")
    if not cleaned:
        return []
    tokens = re.split(r"[,\s]+", cleaned)
    return [tok for tok in tokens if tok and tok.lower() not in {"entries", "entry"}]


def missing_required_entries(required: Sequence[str], available: Sequence[str]) -> List[str]:
    available_set = set(available)
    missing = [req for req in required if req not in available_set]
    return missing


def normalize_scalar_token(value: str) -> str:
    """
    Extract the final scalar token from an entry for comparison against enums.

    `foamDictionary -list` often reports plain tokens without trailing
    semicolons. This helper mirrors the heuristic used by the editor for
    determining scalar types so that enum validation is consistent across
    the TUI and automated checks.
    """

    if not value:
        return ""
    cleaned = value.replace(";", " ").strip()
    if not cleaned:
        return ""
    token = cleaned.split()[-1]
    return token.strip('"')


def read_entry(file_path: Path, key: str) -> str:
    result = run_foam_dictionary(file_path, ["-entry", key])
    if result.returncode != 0:
        raise OpenFOAMError(result.stderr.strip() or f"Failed to read entry {key}.")
    text = result.stdout.strip()

    # Heuristic: for simple scalar entries foamDictionary may echo
    # `key value;`. In that case we only want the value part for
    # editing and for -set operations. For multi-line entries or
    # dictionaries we return the raw text.
    lines = text.splitlines()
    if len(lines) == 1:
        line = lines[0].strip()
        if line:
            # Compare with last component of key (in case of dotted paths).
            key_token = key.split(".")[-1]
            parts = line.split(None, 1)
            if parts and parts[0] == key_token and len(parts) == 2:
                return parts[1].strip()
    return text


def write_entry(file_path: Path, key: str, value: str) -> bool:
    result = run_foam_dictionary(file_path, ["-entry", key, "-set", value])
    return result.returncode == 0


def discover_case_files(case_dir: Path) -> Dict[str, List[Path]]:
    """
    Discover candidate dictionary files in an OpenFOAM case.

    Returns a mapping: section -> list of files.
    Sections: "system", "constant", "0*".
    """
    case_dir = case_dir.resolve()
    sections = {"system": [], "constant": [], "0*": []}  # type: Dict[str, List[Path]]

    system_dir = case_dir / "system"
    if system_dir.is_dir():
        sections["system"] = sorted(
            p for p in system_dir.iterdir() if p.is_file()
        )

    constant_dir = case_dir / "constant"
    if constant_dir.is_dir():
        sections["constant"] = sorted(
            p for p in constant_dir.iterdir() if p.is_file()
        )

    zero_dirs: List[Path] = []
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

    zero_files: List[Path] = []
    for d in zero_dirs:
        zero_files.extend(p for p in d.iterdir() if p.is_file())
    sections["0*"] = sorted(zero_files)

    return sections


@dataclass
class FileCheckResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checked: bool = False


def verify_case(
    case_dir: Path,
    progress: Optional[Callable[[Path], None]] = None,
    result_callback: Optional[Callable[[Path, FileCheckResult], None]] = None,
) -> Dict[Path, FileCheckResult]:
    """
    Run a correctness check over all discovered dictionary files.

    Beyond ensuring the files parse with `foamDictionary -keywords`,
    this inspects each entry recursively to detect missing required
    sub-entries (as hinted by `foamDictionary -info`) and invalid
    enum values (compared against `foamDictionary -list`).
    """

    sections = discover_case_files(case_dir)
    results: Dict[Path, FileCheckResult] = {}
    all_files: List[Path] = []
    for files in sections.values():
        all_files.extend(files)

    for file_path in all_files:
        results[file_path] = FileCheckResult()

    for file_path in all_files:
        result = results[file_path]
        if progress:
            progress(file_path)
        try:
            top_level_keys = list_keywords(file_path)
        except OpenFOAMError as exc:
            msg = str(exc).strip() or "Unknown error"
            result.errors.append(msg)
            result.checked = True
            if result_callback:
                result_callback(file_path, result)
            continue
        except KeyboardInterrupt:
            break

        try:
            _check_entries(file_path, result, top_level_keys)

            if "boundaryField" in top_level_keys:
                patches = list_subkeys(file_path, "boundaryField")
                nested_keys = [f"boundaryField.{patch}" for patch in patches]
                _check_entries(file_path, result, nested_keys)
        except KeyboardInterrupt:
            break
        result.checked = True
        if result_callback:
            result_callback(file_path, result)

    return results


def _check_entries(file_path: Path, result: FileCheckResult, keys: Sequence[str]) -> None:
    for key in keys:
        _check_single_entry(file_path, result, key)


def _check_single_entry(file_path: Path, result: FileCheckResult, key: str) -> None:
    info_lines = get_entry_info(file_path, key)
    required = parse_required_entries(info_lines)
    if required:
        subkeys = list_subkeys(file_path, key)
        missing = missing_required_entries(required, subkeys)
        if missing:
            result.errors.append(f"{key}: missing required entries: {', '.join(missing)}")

    enum_values = get_entry_enum_values(file_path, key)
    if enum_values:
        try:
            value = read_entry(file_path, key)
        except OpenFOAMError as exc:
            result.errors.append(f"{key}: {exc}")
            return

        token = normalize_scalar_token(value)
        allowed = {val.strip() for val in enum_values if val.strip()}
        if token and token not in allowed:
            allowed_list = ", ".join(sorted(allowed))
            result.errors.append(
                f"{key}: invalid value '{token}'. Allowed: {allowed_list}"
            )
