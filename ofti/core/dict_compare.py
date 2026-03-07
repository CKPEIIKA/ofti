from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ofti.foamlib import fallback as foam_fallback

_EXPLICIT_DICT_FILES = {
    "0/include/initialConditions",
    "constant/chemistryProperties",
    "constant/thermo2TModel",
    "constant/thermophysicalProperties",
    "system/controlDict",
    "system/fvSchemes",
    "system/fvSolution",
    "system/sampleDict",
}
_ROOT_COMPARE_FILES = {
    "maxCoSchedule.dat",
    "pointPriority",
    "ofti.postprocessing",
    "ofti.tools",
}
_IGNORED_PARTS = {".git", ".ofti", "__pycache__", "postProcessing"}


@dataclass(frozen=True)
class ValueDiff:
    key: str
    left: str
    right: str


@dataclass(frozen=True)
class DictDiff:
    rel_path: str
    missing_in_left: list[str]
    missing_in_right: list[str]
    value_diffs: list[ValueDiff]
    kind: str = "dict"
    left_hash: str | None = None
    right_hash: str | None = None
    error: str | None = None


def compare_case_dicts(left_case: Path, right_case: Path) -> list[DictDiff]:
    left_map = _case_file_map(left_case)
    right_map = _case_file_map(right_case)
    all_paths = sorted(set(left_map) | set(right_map))
    diffs: list[DictDiff] = []

    for rel_path in all_paths:
        left_path = left_map.get(rel_path)
        right_path = right_map.get(rel_path)
        if left_path is None:
            diffs.append(
                DictDiff(
                    rel_path,
                    missing_in_left=[rel_path],
                    missing_in_right=[],
                    value_diffs=[],
                    kind="missing",
                ),
            )
            continue
        if right_path is None:
            diffs.append(
                DictDiff(
                    rel_path,
                    missing_in_left=[],
                    missing_in_right=[rel_path],
                    value_diffs=[],
                    kind="missing",
                ),
            )
            continue
        if _is_dictionary(rel_path, left_path, right_path):
            diff = _compare_dictionary_file(rel_path, left_path, right_path)
        else:
            diff = _compare_raw_file(rel_path, left_path, right_path)
        if diff is None:
            continue
        diffs.append(diff)

    return diffs


def _case_file_map(case_path: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    case_root = case_path.resolve()
    for name in ("system", "constant"):
        section = case_root / name
        if section.is_dir():
            _collect_files(case_root, section, files)
    for entry in case_root.iterdir():
        if not entry.is_dir():
            if entry.name in _ROOT_COMPARE_FILES:
                files[entry.name] = entry
            continue
        if entry.name.startswith("0"):
            _collect_files(case_root, entry, files)
    return files


def _collect_files(case_root: Path, section: Path, files: dict[str, Path]) -> None:
    for path in section.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(case_root).as_posix()
        if _skip_rel(rel):
            continue
        files[rel] = path


def _skip_rel(rel_path: str) -> bool:
    parts = rel_path.split("/")
    for part in parts:
        lowered = part.lower()
        if part in _IGNORED_PARTS:
            return True
        if lowered.startswith("processor"):
            return True
    return False


def _is_dictionary(rel_path: str, left_path: Path, right_path: Path) -> bool:
    normalized = rel_path.replace("\\", "/")
    if normalized in _EXPLICIT_DICT_FILES:
        return True
    if normalized.endswith("/include/initialConditions"):
        return True
    if left_path.suffix in {".dat", ".csv", ".json", ".txt"}:
        return False
    for candidate in (left_path, right_path):
        try:
            head = candidate.read_text(encoding="utf-8", errors="ignore")[:4096]
        except OSError:
            continue
        if "FoamFile" in head:
            return True
    return False


def _compare_dictionary_file(rel_path: str, left_path: Path, right_path: Path) -> DictDiff | None:
    left_data, left_error = _load_dict(left_path)
    right_data, right_error = _load_dict(right_path)
    left_flat = _flatten_mapping(left_data) if left_data else {}
    right_flat = _flatten_mapping(right_data) if right_data else {}
    if not left_flat:
        left_flat = _raw_flatten_pairs(left_path)
    if not right_flat:
        right_flat = _raw_flatten_pairs(right_path)

    if left_flat or right_flat:
        left_keys = set(left_flat)
        right_keys = set(right_flat)
    else:
        left_keys = _raw_key_scan(left_path)
        right_keys = _raw_key_scan(right_path)

    missing_in_left = sorted(right_keys - left_keys)
    missing_in_right = sorted(left_keys - right_keys)
    value_diffs: list[ValueDiff] = []
    for key in sorted(left_keys & right_keys):
        left_value = left_flat.get(key)
        right_value = right_flat.get(key)
        if left_value is None or right_value is None:
            continue
        if _normalize_scalar(left_value) == _normalize_scalar(right_value):
            continue
        value_diffs.append(ValueDiff(key=key, left=left_value, right=right_value))

    errors = [item for item in (left_error, right_error) if item]
    error_text = "; ".join(errors) if errors else None
    if not missing_in_left and not missing_in_right and not value_diffs and error_text is None:
        return None
    return DictDiff(
        rel_path=rel_path,
        missing_in_left=missing_in_left,
        missing_in_right=missing_in_right,
        value_diffs=value_diffs,
        kind="dict",
        error=error_text,
    )


def _compare_raw_file(rel_path: str, left_path: Path, right_path: Path) -> DictDiff | None:
    left_hash = _hash_file(left_path)
    right_hash = _hash_file(right_path)
    if left_hash == right_hash:
        return None
    return DictDiff(
        rel_path=rel_path,
        missing_in_left=[],
        missing_in_right=[],
        value_diffs=[],
        kind="file",
        left_hash=left_hash,
        right_hash=right_hash,
        error=None,
    )


def _load_dict(path: Path) -> tuple[dict[str, object] | None, str | None]:
    try:
        data = foam_fallback.parse_mapping(path)
    except Exception as exc:
        return None, f"{path.name}: parse failed ({exc})"
    return data, None


def _flatten_mapping(data: dict[str, object], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        if key == "FoamFile":
            continue
        child_key = f"{prefix}.{key}" if prefix else key
        nested_dict = _as_str_object_dict(value)
        if nested_dict is not None:
            nested = _flatten_mapping(nested_dict, child_key)
            if nested:
                flat.update(nested)
                continue
        flat[child_key] = _value_text(value)
    return flat


def _value_text(value: object) -> str:
    if isinstance(value, list):
        return "(" + " ".join(str(item) for item in value) + ")"
    return str(value).strip()


def _as_str_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return cast(dict[str, object], value)


def _raw_key_scan(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    keys: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line or line.startswith(("/*", "*", "#", "{", "}", "(", ")", ";")):
            continue
        if "{" in line:
            token = line.split("{", 1)[0].strip().split()[:1]
            if token:
                candidate = token[0].strip('"')
                if _is_key_token(candidate):
                    keys.add(candidate)
            continue
        parts = line.replace(";", " ").split()
        if not parts:
            continue
        candidate = parts[0].strip('"')
        if _is_key_token(candidate):
            keys.add(candidate)
    return keys


def _raw_flatten_pairs(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    tokens = _raw_flatten_tokens(text)
    pairs: dict[str, str] = {}
    stack: list[str] = []
    index = 0
    while index < len(tokens):
        part = tokens[index]
        if part == "}":
            if stack:
                stack.pop()
            index += 1
            continue
        if part in {"{", ";"}:
            index += 1
            continue
        key = part.strip('"')
        if not _is_key_token(key):
            index += 1
            continue
        index += 1
        index, opened_block, value_tokens = _consume_raw_value(tokens, index)
        if opened_block:
            stack.append(key)
            continue
        if value_tokens:
            value = _normalize_scalar(" ".join(value_tokens))
            full_key = ".".join([*stack, key]) if stack else key
            pairs[full_key] = value
    return pairs


def _raw_flatten_tokens(text: str) -> list[str]:
    cleaned = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    cleaned = re.sub(r"//.*", "", cleaned)
    cleaned = "\n".join(line for line in cleaned.splitlines() if not line.strip().startswith("#"))
    return re.findall(r'"[^"]*"|[{};]|[^\s{};]+', cleaned)


def _consume_raw_value(tokens: list[str], index: int) -> tuple[int, bool, list[str]]:
    values: list[str] = []
    idx = index
    while idx < len(tokens):
        part = tokens[idx]
        if part == "{":
            return idx + 1, True, []
        if part in {";", "}"}:
            break
        values.append(part.strip('"'))
        idx += 1
    if idx < len(tokens) and tokens[idx] == ";":
        idx += 1
    return idx, False, values


def _is_key_token(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_./:-]*", value))


def _normalize_scalar(value: str) -> str:
    return " ".join(value.replace(";", " ").split())


def _hash_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()
