from __future__ import annotations

import re
from pathlib import Path


def available() -> bool:
    return True


def list_keywords(file_path: Path) -> list[str]:
    text = _read_text(file_path)
    if text is None:
        return []
    data = _parse_mapping(text)
    return list(data.keys())


def list_subkeys(file_path: Path, entry: str) -> list[str]:
    node = read_entry_node(file_path, entry)
    if isinstance(node, dict):
        return list(node.keys())
    return []


def read_entry(file_path: Path, key: str) -> str:
    node = read_entry_node(file_path, key)
    if isinstance(node, dict):
        return _dump_dict(node)
    if isinstance(node, list):
        key_name = _split_key(key)[-1] if _split_key(key) else ""
        if key_name == "dimensions":
            return _dump_list(node, bracket="[]")
        return _dump_list(node)
    return str(node)


def read_entry_node(file_path: Path, key: str) -> object:
    text = _read_text(file_path)
    if text is None:
        raise KeyError(key)
    data = _parse_mapping(text)
    node: object = data
    for part in _split_key(key):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(key)
        node = node[part]
    return node


def read_field_entry(file_path: Path, key: str) -> str:
    return read_entry(file_path, key)


def read_field_entry_node(file_path: Path, key: str) -> object:
    return read_entry_node(file_path, key)


def write_entry(file_path: Path, key: str, value: str) -> bool:
    text = _read_text(file_path)
    if text is None:
        return False
    parts = _split_key(key)
    if not parts:
        return False
    parent_parts = parts[:-1]
    leaf = parts[-1]
    parent_span = _find_block_span(text, parent_parts) if parent_parts else None
    if parent_parts and parent_span is None:
        return False
    replacement = _normalize_value(value)
    updated = _set_scalar_entry(text, parent_span, leaf, replacement)
    if updated is None:
        return False
    try:
        file_path.write_text(updated)
    except OSError:
        return False
    return True


def write_field_entry(file_path: Path, key: str, value: str) -> bool:
    return write_entry(file_path, key, value)


def parse_boundary_file(path: Path) -> tuple[list[str], dict[str, str]]:
    text = _read_text(path)
    if text is None:
        return [], {}
    patches: list[str] = []
    patch_types: dict[str, str] = {}
    in_entries = False
    current_patch: str | None = None
    brace_depth = 0
    pending_patch: str | None = None
    for raw in text.splitlines():
        line = _strip_comments(raw).strip()
        if not line or line.startswith("FoamFile"):
            continue
        if not in_entries:
            if line == "(" or line.endswith("("):
                in_entries = True
            continue
        if line.startswith(")"):
            break
        if current_patch is None:
            if pending_patch and line.startswith("{"):
                current_patch = pending_patch
                pending_patch = None
                patches.append(current_patch)
                brace_depth = 1
                continue
            name = _match_patch_start(line)
            if name:
                current_patch = name
                patches.append(name)
                if "type" in line and ";" in line:
                    tokens = line.replace(";", " ").split()
                    if len(tokens) >= 4:
                        patch_types[current_patch] = tokens[3]
                brace_depth = line.count("{") - line.count("}")
                if brace_depth <= 0:
                    current_patch = None
                    brace_depth = 0
                continue
            if _looks_like_patch_name(line):
                pending_patch = line.strip('"')
            continue
        if "type" in line and ";" in line:
            tokens = line.replace(";", " ").split()
            if len(tokens) >= 2 and tokens[0] == "type":
                patch_types[current_patch] = tokens[1]
        brace_depth += line.count("{")
        brace_depth -= line.count("}")
        if brace_depth <= 0:
            current_patch = None
            brace_depth = 0
    return patches, patch_types


def rename_boundary_patch(path: Path, old: str, new: str) -> bool:
    text = _read_text(path)
    if text is None:
        return False
    pattern = re.compile(rf"(?m)^(\s*){re.escape(old)}(\s*\{{)")
    updated, count = pattern.subn(rf"\1{new}\2", text)
    if count == 0:
        return False
    try:
        path.write_text(updated)
    except OSError:
        return False
    return True


def change_boundary_patch_type(path: Path, patch: str, new_type: str) -> bool:
    text = _read_text(path)
    if text is None:
        return False
    span = _find_block_span(text, [patch])
    if span is None:
        return False
    updated = _set_scalar_entry(text, span, "type", new_type)
    if updated is None:
        return False
    try:
        path.write_text(updated)
    except OSError:
        return False
    return True


def rename_boundary_field_patch(file_path: Path, old: str, new: str) -> bool:
    text = _read_text(file_path)
    if text is None:
        return False
    span = _find_block_span(text, ["boundaryField"])
    if span is None:
        return False
    start, end = span
    inner = text[start:end]
    pattern = re.compile(rf"(?m)^(\s*)\"?{re.escape(old)}\"?(\s*\{{)")
    updated_inner, count = pattern.subn(rf"\1{new}\2", inner)
    if count == 0:
        return False
    updated = text[:start] + updated_inner + text[end:]
    try:
        file_path.write_text(updated)
    except OSError:
        return False
    return True


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(errors="ignore")
    except OSError:
        return None


def _split_key(key: str) -> list[str]:
    return [part for part in key.split(".") if part]


def _normalize_value(value: str) -> str:
    text = value.strip().rstrip(";").strip()
    parsed = _parse_uniform(text)
    if parsed is not None:
        return parsed
    return text


def _parse_uniform(value: str) -> str | None:
    if not value.startswith("uniform"):
        return None
    payload = value[len("uniform") :].strip()
    if payload.startswith("(") and payload.endswith(")"):
        inner = payload[1:-1].strip()
        if not inner:
            return "uniform ()"
        parts = inner.split()
        floats: list[str] = []
        for item in parts:
            try:
                floats.append(f"{float(item):.1f}")
            except ValueError:
                return None
        return f"uniform ({' '.join(floats)})"
    try:
        return f"uniform {float(payload):.1f}"
    except ValueError:
        return None


def _dump_dict(node: dict[str, object]) -> str:
    lines = ["{"]
    for key, value in node.items():
        if isinstance(value, dict):
            lines.append(f"    {key}")
            block = _dump_dict(value).splitlines()
            lines.extend([f"    {line}" for line in block])
            continue
        lines.append(f"    {key} {_dump_scalar(value)};")
    lines.append("}")
    return "\n".join(lines)


def _dump_list(values: list[object], bracket: str = "()") -> str:
    left, right = bracket[0], bracket[1]
    return left + " ".join(str(item) for item in values) + right


def _dump_scalar(value: object) -> str:
    if isinstance(value, list):
        return _dump_list(value)
    return str(value)


def _parse_mapping(text: str) -> dict[str, object]:
    tokens = _tokenize(text)
    data, _ = _parse_entries(tokens, 0)
    return data


def _tokenize(text: str) -> list[str]:
    cleaned = _strip_block_comments(text)
    cleaned = re.sub(r"//.*", "", cleaned)
    return re.findall(r'"[^"]*"|[{}();]|[^\s{}();]+', cleaned)


def _strip_block_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _parse_entries(tokens: list[str], index: int) -> tuple[dict[str, object], int]:
    data: dict[str, object] = {}
    i = index
    while i < len(tokens):
        tok = tokens[i]
        if tok == "}":
            return data, i + 1
        if tok in {";", "{", ")"}:
            i += 1
            continue
        if tok == "(":
            i = _skip_paren(tokens, i + 1)
            continue
        key = _strip_quotes(tok)
        i += 1
        if i >= len(tokens):
            break
        cur = tokens[i]
        if cur == "{":
            nested, i = _parse_entries(tokens, i + 1)
            data[key] = nested
            continue
        value_tokens: list[str] = []
        while i < len(tokens) and tokens[i] != ";":
            part = tokens[i]
            if part == "{":
                nested, i = _parse_entries(tokens, i + 1)
                data[key] = nested
                break
            if part == "(":
                content, i = _collect_paren(tokens, i + 1)
                value_tokens.append(f"({content})")
                continue
            if part == "}":
                break
            value_tokens.append(_strip_quotes(part))
            i += 1
        else:
            # no break
            pass
        if key not in data:
            data[key] = _convert_scalar(" ".join(value_tokens).strip())
        if i < len(tokens) and tokens[i] == ";":
            i += 1
    return data, i


def _skip_paren(tokens: list[str], index: int) -> int:
    depth = 1
    i = index
    while i < len(tokens):
        if tokens[i] == "(":
            depth += 1
        elif tokens[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def _collect_paren(tokens: list[str], index: int) -> tuple[str, int]:
    depth = 1
    i = index
    parts: list[str] = []
    while i < len(tokens):
        tok = tokens[i]
        if tok == "(":
            depth += 1
            parts.append(tok)
            i += 1
            continue
        if tok == ")":
            depth -= 1
            if depth == 0:
                return " ".join(parts).strip(), i + 1
            parts.append(tok)
            i += 1
            continue
        parts.append(_strip_quotes(tok))
        i += 1
    return " ".join(parts).strip(), i


def _convert_scalar(value: str) -> object:
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        body = stripped[1:-1].strip()
        if not body:
            return []
        items: list[object] = []
        for part in body.split():
            try:
                number = float(part)
            except ValueError:
                return stripped
            items.append(int(number) if number.is_integer() else number)
        return items
    return stripped


def _strip_quotes(token: str) -> str:
    return token[1:-1] if token.startswith('"') and token.endswith('"') else token


def _find_block_span(text: str, path: list[str]) -> tuple[int, int] | None:
    start = 0
    end = len(text)
    for key in path:
        span = _find_named_block(text, key, start, end)
        if span is None:
            return None
        start, end = span
    return start, end


def _find_named_block(text: str, key: str, start: int, end: int) -> tuple[int, int] | None:
    segment = text[start:end]
    pattern = re.compile(rf'(?m)(^|\s)"?{re.escape(key)}"?\s*\{{')
    match = pattern.search(segment)
    if not match:
        return None
    open_brace = start + match.end() - 1
    close_brace = _match_brace(text, open_brace)
    if close_brace is None:
        return None
    return open_brace + 1, close_brace


def _match_brace(text: str, open_brace: int) -> int | None:
    depth = 0
    for idx in range(open_brace, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _set_scalar_entry(
    text: str,
    parent_span: tuple[int, int] | None,
    key: str,
    value: str,
) -> str | None:
    if parent_span is None:
        segment = text
        base = 0
    else:
        segment = text[parent_span[0]:parent_span[1]]
        base = parent_span[0]
    pattern = re.compile(rf'(?m)^(\s*)"?{re.escape(key)}"?\s+([^;{{}}]+);')
    match = pattern.search(segment)
    if match:
        leading = match.group(1)
        replacement = f"{leading}{key} {value};"
        start = base + match.start()
        end = base + match.end()
        return text[:start] + replacement + text[end:]
    insert_at = base + len(segment)
    insertion = f"\n    {key} {value};\n"
    if parent_span is None:
        return text + insertion
    return text[:insert_at] + insertion + text[insert_at:]


def _strip_comments(line: str) -> str:
    if "//" in line:
        return line.split("//", 1)[0]
    return line


def _match_patch_start(line: str) -> str | None:
    match = re.match(r'^"?([A-Za-z0-9_./-]+)"?\s*\{', line)
    return match.group(1) if match else None


def _looks_like_patch_name(line: str) -> bool:
    return bool(re.match(r'^"?[A-Za-z0-9_./-]+"?$', line))
