from __future__ import annotations


def find_suspicious_lines(content: str) -> list[str]:  # noqa: C901
    warnings: list[str] = []
    brace_depth = 0
    header_done = False
    in_block_comment = False

    lines = content.splitlines()

    def next_significant_line(idx: int) -> str | None:
        for candidate in lines[idx + 1 :]:
            stripped = candidate.strip()
            if not stripped:
                continue
            if stripped.startswith(("//", "/*", "*")):
                continue
            return stripped
        return None

    def consume_header_line(stripped: str, done: bool) -> tuple[bool, bool]:
        if done:
            return True, False
        if not stripped or stripped.startswith(("/*", "*", "|", "\\", "//")):
            return False, True
        if "foamfile" in stripped.lower():
            return True, True
        return True, False

    def strip_block_comments(line: str, in_block: bool) -> tuple[str, bool]:
        cleaned = ""
        remainder = line
        while remainder:
            if in_block:
                end = remainder.find("*/")
                if end == -1:
                    return "", True
                remainder = remainder[end + 2 :]
                in_block = False
                continue
            start = remainder.find("/*")
            if start == -1:
                cleaned += remainder
                break
            cleaned += remainder[:start]
            remainder = remainder[start + 2 :]
            end = remainder.find("*/")
            if end == -1:
                return cleaned, True
            remainder = remainder[end + 2 :]
        return cleaned, in_block

    def strip_line_comment(line: str) -> str:
        return line.split("//", 1)[0] if "//" in line else line

    def should_skip_semicolon_check(stripped_line: str, line: str, next_line: str | None) -> bool:
        if stripped_line.startswith(("#include", "#ifdef")):
            return True
        if "{" in line and "}" in line:
            return True
        if stripped_line.endswith((";", "{", "}")):
            return True
        if stripped_line.endswith(("(", ")")):
            return True
        return next_line == "{"

    for idx, raw in enumerate(lines, 1):
        stripped = raw.strip()
        header_done, skip = consume_header_line(stripped, header_done)
        if skip:
            continue

        line, in_block_comment = strip_block_comments(raw, in_block_comment)
        if in_block_comment:
            continue

        line = strip_line_comment(line)
        stripped_line = line.strip()
        if not stripped_line:
            continue

        for ch in line:
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth < 0:
                    warnings.append(f"Line {idx}: unexpected '}}'.")
                    brace_depth = 0

        if should_skip_semicolon_check(stripped_line, line, next_significant_line(idx - 1)):
            continue

        warnings.append(f"Line {idx}: missing ';'? -> {stripped_line[:60]}")

    if brace_depth > 0:
        warnings.append("File ends with unmatched '{'.")

    return warnings
