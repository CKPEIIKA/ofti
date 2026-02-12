from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.foamlib import fallback

class FoamlibUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("foamlib is not available")


try:  # pragma: no cover - exercised in tests when installed
    from foamlib import FoamFieldFile, FoamFile
    FOAMLIB_AVAILABLE = True
except Exception:  # pragma: no cover - optional fallback
    FoamFile = None  # type: ignore[assignment]
    FoamFieldFile = None  # type: ignore[assignment]
    FOAMLIB_AVAILABLE = False

try:  # pragma: no cover - optional preprocessing extras
    from foamlib.preprocessing import system as foamlib_system
    from foamlib.preprocessing.of_dict import FoamDictAssignment, FoamDictInstruction
    FOAMLIB_PREPROCESSING = True
    FOAMLIB_SYSTEM = True
except Exception:  # pragma: no cover - optional fallback
    FoamDictAssignment = None  # type: ignore[assignment]
    FoamDictInstruction = None  # type: ignore[assignment]
    foamlib_system = None  # type: ignore[assignment]
    FOAMLIB_PREPROCESSING = False
    FOAMLIB_SYSTEM = False


def available() -> bool:
    return FOAMLIB_AVAILABLE or fallback.available()


def is_foam_file(path: Path) -> bool:
    try:
        head = path.read_text(errors="ignore")[:2048]
    except OSError:
        return False
    return "FoamFile" in head


def is_field_file(path: Path) -> bool:
    if not is_foam_file(path):
        return False
    try:
        head = path.read_text(errors="ignore")[:4096]
    except OSError:
        return False
    return "internalField" in head or "boundaryField" in head


def _split_key(key: str) -> tuple[str, ...]:
    return tuple(part for part in key.split(".") if part)


def _foam_file(path: Path) -> Any:
    if not FOAMLIB_AVAILABLE or FoamFile is None:
        raise FoamlibUnavailableError()
    return FoamFile(path)


def _foam_field_file(path: Path) -> Any:
    if not FOAMLIB_AVAILABLE or FoamFieldFile is None:
        raise FoamlibUnavailableError()
    return FoamFieldFile(path)


def list_keywords(file_path: Path) -> list[str]:
    if not FOAMLIB_AVAILABLE:
        return fallback.list_keywords(file_path)
    foam_file = _foam_file(file_path)
    return [key for key in foam_file if isinstance(key, str)]


def list_subkeys(file_path: Path, entry: str) -> list[str]:
    if not FOAMLIB_AVAILABLE:
        return fallback.list_subkeys(file_path, entry)
    foam_file = _foam_file(file_path)
    key_parts = _split_key(entry)
    node = foam_file.getone(key_parts if key_parts else None)
    if node is None:
        return []
    if hasattr(node, "keys"):
        return [key for key in node if isinstance(key, str)]
    return []


def read_entry(file_path: Path, key: str) -> str:
    if not FOAMLIB_AVAILABLE:
        return fallback.read_entry(file_path, key)
    foam_file = _foam_file(file_path)
    key_parts = _split_key(key)
    node = foam_file.getone(key_parts if key_parts else None)
    if node is None:
        raise KeyError(key)
    key_name = key_parts[-1] if key_parts else ""
    return _dump_entry_value(key_name, node)


def read_entry_node(file_path: Path, key: str) -> object:
    if not FOAMLIB_AVAILABLE:
        return fallback.read_entry_node(file_path, key)
    foam_file = _foam_file(file_path)
    key_parts = _split_key(key)
    node = foam_file.getone(key_parts if key_parts else None)
    if node is None:
        raise KeyError(key)
    return node


def read_field_entry(file_path: Path, key: str) -> str:
    if not FOAMLIB_AVAILABLE:
        return fallback.read_field_entry(file_path, key)
    field_file = _foam_field_file(file_path)
    key_parts = _split_key(key)
    node = field_file.getone(key_parts if key_parts else None)
    if node is None:
        raise KeyError(key)
    key_name = key_parts[-1] if key_parts else ""
    return _dump_entry_value(key_name, node)


def read_field_entry_node(file_path: Path, key: str) -> object:
    if not FOAMLIB_AVAILABLE:
        return fallback.read_field_entry_node(file_path, key)
    field_file = _foam_field_file(file_path)
    key_parts = _split_key(key)
    node = field_file.getone(key_parts if key_parts else None)
    if node is None:
        raise KeyError(key)
    return node


def _foamlib_can_write(value: str) -> bool:
    value = value.strip()
    if not value:
        return True
    if value.startswith("{"):
        return False
    if value.startswith("uniform"):
        return False
    if any(ch in value for ch in "(){}"):  # arrays/vectors/dicts
        return False
    return len(value.split()) == 1


def _parse_uniform_value(value: str) -> object | None:
    text = value.strip()
    if text.startswith("uniform"):
        text = text[len("uniform") :].strip()
    if text.startswith("(") and text.endswith(")"):
        inner = text[1:-1].strip()
        if not inner:
            return None
        parts = inner.split()
        try:
            return [float(part) for part in parts]
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def write_entry(file_path: Path, key: str, value: str) -> bool:
    if not FOAMLIB_AVAILABLE:
        return fallback.write_entry(file_path, key, value)
    if FOAMLIB_PREPROCESSING:
        ok = _write_entry_with_assignment(file_path, key, value, case_path=None)
        if ok:
            return True
    foam_file = _foam_file(file_path)
    key_parts = _split_key(key)
    cleaned = value.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    parsed = _parse_uniform_value(cleaned)
    if parsed is not None:
        with foam_file:
            foam_file[key_parts if key_parts else None] = parsed
        return True
    if not _foamlib_can_write(cleaned):
        return False
    with foam_file:
        foam_file[key_parts if key_parts else None] = cleaned
    return True


def write_field_entry(file_path: Path, key: str, value: str) -> bool:
    if not FOAMLIB_AVAILABLE:
        return fallback.write_field_entry(file_path, key, value)
    field_file = _foam_field_file(file_path)
    cleaned = value.strip()
    if not cleaned:
        return False
    key_parts = _split_key(key)
    key_name = key_parts[-1] if key_parts else ""
    if cleaned.startswith("{"):
        payload = f"{key_name}\n{cleaned}\n"
    else:
        if not cleaned.endswith(";"):
            cleaned = f"{cleaned};"
        payload = f"{key_name} {cleaned}"
    try:
        parsed = FoamFieldFile.loads(payload, include_header=False).get(key_name)
    except Exception:
        return False
    if parsed is None:
        return False
    with field_file:
        field_file[key_parts if key_parts else None] = parsed
    return True


def apply_assignment(
    case_path: Path,
    file_path: Path,
    key_path: list[str],
    value: str,
) -> bool:
    if not FOAMLIB_PREPROCESSING:
        return False
    key = ".".join(key_path)
    return _write_entry_with_assignment(file_path, key, value, case_path=case_path)


def _write_entry_with_assignment(
    file_path: Path,
    key: str,
    value: str,
    *,
    case_path: Path | None,
) -> bool:
    if not FOAMLIB_PREPROCESSING or FoamDictAssignment is None or FoamDictInstruction is None:
        return False
    cleaned = value.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    parsed = _parse_uniform_value(cleaned)
    payload: object
    if parsed is not None:
        payload = parsed
    else:
        if not _foamlib_can_write(cleaned):
            return False
        payload = cleaned
    try:
        instruction = _instruction_for_file(
            file_path,
            list(_split_key(key)),
            case_path=case_path,
        )
        assignment = FoamDictAssignment(instruction=instruction, value=payload)
        assignment.set_value()
    except Exception:
        return False
    return True


def _instruction_for_file(
    file_path: Path,
    keys: list[str],
    *,
    case_path: Path | None,
) -> Any:
    rel_path: Path
    if case_path is not None:
        try:
            rel_path = file_path.relative_to(case_path)
        except ValueError:
            rel_path = file_path
    else:
        rel_path = file_path
    helper = _system_helper_for(rel_path)
    if helper is not None:
        return helper(keys)
    return FoamDictInstruction(file_name=rel_path, keys=keys)


def _system_helper_for(rel_path: Path) -> Any | None:
    if not FOAMLIB_SYSTEM or foamlib_system is None:
        return None
    normalized = rel_path.as_posix()
    mapping = {
        "system/controlDict": foamlib_system.control_dict,
        "system/fvSchemes": foamlib_system.fv_schemes,
        "system/fvSolution": foamlib_system.fv_solution,
        "system/simulationParameters": foamlib_system.simulation_parameters,
    }
    return mapping.get(normalized)


def _dump_entry_value(key_name: str, node: object) -> str:
    text = FoamFile.dumps({key_name: node}, ensure_header=False).decode().strip()
    lines = text.splitlines()
    if len(lines) == 1 and key_name:
        line = lines[0].strip()
        parts = line.split(None, 1)
        if parts and parts[0] == key_name and len(parts) == 2:
            return parts[1].strip()
    return text


def parse_boundary_file(path: Path) -> tuple[list[str], dict[str, str]]:
    if not FOAMLIB_AVAILABLE:
        return fallback.parse_boundary_file(path)
    foam_file = _foam_file(path)
    entries = foam_file.getone(None)
    patches: list[str] = []
    patch_types: dict[str, str] = {}
    if not isinstance(entries, list):
        return patches, patch_types
    for item in entries:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        name, data = item
        if not isinstance(name, str):
            continue
        patches.append(name)
        if isinstance(data, dict):
            entry_type = data.get("type")
            if isinstance(entry_type, str):
                patch_types[name] = entry_type
    return patches, patch_types


def rename_boundary_patch(path: Path, old: str, new: str) -> bool:
    if not FOAMLIB_AVAILABLE:
        return fallback.rename_boundary_patch(path, old, new)
    foam_file = _foam_file(path)
    entries = foam_file.getone(None)
    if not isinstance(entries, list):
        return False
    updated: list[tuple[object, object]] = []
    found = False
    for item in entries:
        if not isinstance(item, tuple) or len(item) != 2:
            updated.append(item)
            continue
        name, data = item
        if name == old:
            updated.append((new, data))
            found = True
        else:
            updated.append(item)
    if not found:
        return False
    with foam_file:
        foam_file[None] = updated
    return True


def change_boundary_patch_type(path: Path, patch: str, new_type: str) -> bool:
    if not FOAMLIB_AVAILABLE:
        return fallback.change_boundary_patch_type(path, patch, new_type)
    foam_file = _foam_file(path)
    entries = foam_file.getone(None)
    if not isinstance(entries, list):
        return False
    updated: list[tuple[object, object]] = []
    found = False
    for item in entries:
        if not isinstance(item, tuple) or len(item) != 2:
            updated.append(item)
            continue
        name, data = item
        if name == patch and isinstance(data, dict):
            data = dict(data)
            data["type"] = new_type
            updated.append((name, data))
            found = True
        else:
            updated.append(item)
    if not found:
        return False
    with foam_file:
        foam_file[None] = updated
    return True


def rename_boundary_field_patch(file_path: Path, old: str, new: str) -> bool:
    if not FOAMLIB_AVAILABLE:
        return fallback.rename_boundary_field_patch(file_path, old, new)
    field_file = _foam_field_file(file_path)
    key_old = ("boundaryField", old)
    key_new = ("boundaryField", new)
    try:
        value = field_file.getone(key_old)
    except Exception:
        value = None
    if value is None:
        return False
    with field_file:
        field_file[key_new] = value
        try:
            del field_file[key_old]
        except Exception:
            return False
    return True
