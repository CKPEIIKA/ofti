from __future__ import annotations


def find_suspicious_lines(content: str) -> list[str]:
    warnings: list[str] = []
    state = _SyntaxState(lines=content.splitlines())
    for idx, raw in enumerate(state.lines, 1):
        state.header_done, skip = _consume_header_line(raw.strip(), state.header_done)
        if skip:
            continue
        line = state.code_line(raw)
        if not line:
            continue
        _update_braces(line, idx, state, warnings)
        if _should_skip_semicolon_check(line.strip(), line, state.next_significant_line(idx - 1)):
            continue
        warnings.append(f"Line {idx}: missing ';'? -> {line.strip()[:60]}")
    if state.brace_depth > 0:
        warnings.append("File ends with unmatched '{'.")
    return warnings


class _SyntaxState:
    def __init__(self, *, lines: list[str]) -> None:
        self.lines = lines
        self.brace_depth = 0
        self.header_done = False
        self.in_block_comment = False

    def next_significant_line(self, idx: int) -> str | None:
        for candidate in self.lines[idx + 1 :]:
            stripped = candidate.strip()
            if stripped and not stripped.startswith(("//", "/*", "*")):
                return stripped
        return None

    def code_line(self, raw: str) -> str:
        line, self.in_block_comment = _strip_block_comments(raw, self.in_block_comment)
        if self.in_block_comment:
            return ""
        return _strip_line_comment(line).strip()


def _consume_header_line(stripped: str, done: bool) -> tuple[bool, bool]:
    if done:
        return True, False
    if not stripped or stripped.startswith(("/*", "*", "|", "\\", "//")):
        return False, True
    if "foamfile" in stripped.lower():
        return True, True
    return True, False


def _strip_block_comments(line: str, in_block: bool) -> tuple[str, bool]:
    cleaned = ""
    remainder = line
    while remainder:
        if in_block:
            remainder, in_block = _consume_block_comment_tail(remainder)
            if in_block:
                return "", True
            continue
        start = remainder.find("/*")
        if start == -1:
            return cleaned + remainder, False
        cleaned += remainder[:start]
        remainder = remainder[start + 2 :]
        end = remainder.find("*/")
        if end == -1:
            return cleaned, True
        remainder = remainder[end + 2 :]
    return cleaned, in_block


def _consume_block_comment_tail(remainder: str) -> tuple[str, bool]:
    end = remainder.find("*/")
    if end == -1:
        return "", True
    return remainder[end + 2 :], False


def _strip_line_comment(line: str) -> str:
    return line.split("//", 1)[0] if "//" in line else line


def _update_braces(line: str, idx: int, state: _SyntaxState, warnings: list[str]) -> None:
    for ch in line:
        if ch == "{":
            state.brace_depth += 1
        elif ch == "}":
            state.brace_depth -= 1
            if state.brace_depth < 0:
                warnings.append(f"Line {idx}: unexpected '}}'.")
                state.brace_depth = 0


def _should_skip_semicolon_check(stripped_line: str, line: str, next_line: str | None) -> bool:
    if stripped_line.startswith(("#include", "#ifdef")):
        return True
    if "{" in line and "}" in line:
        return True
    if stripped_line.endswith((";", "{", "}", "(", ")")):
        return True
    return next_line == "{"
