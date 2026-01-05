import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional


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
    result = subprocess.run(cmd, capture_output=True, text=True)
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
        if entry.is_dir() and entry.name.startswith("0"):
            zero_dirs.append(entry)

    zero_files: List[Path] = []
    for d in zero_dirs:
        zero_files.extend(p for p in d.iterdir() if p.is_file())
    sections["0*"] = sorted(zero_files)

    return sections


def verify_case(case_dir: Path) -> Dict[Path, Optional[str]]:
    """
    Run a simple correctness check over all discovered dictionary files.

    For each file, try to list its keywords with foamDictionary.
    Returns a mapping of file path -> error message (or None if OK).
    """
    sections = discover_case_files(case_dir)
    results: Dict[Path, Optional[str]] = {}

    for files in sections.values():
        for file_path in files:
            try:
                list_keywords(file_path)
            except OpenFOAMError as exc:
                msg = str(exc).strip() or "Unknown error"
                results[file_path] = msg
            else:
                results[file_path] = None

    return results
