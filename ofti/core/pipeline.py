from __future__ import annotations

import shlex
from collections.abc import Callable, Iterable
from pathlib import Path

from ofti.core.tool_dicts_service import apply_assignment_or_write
from ofti.foam.subprocess_utils import run_trusted

PIPELINE_FILENAME = "Allrun"
PIPELINE_HEADER = "# OFTI-PIPELINE"
PIPELINE_SET_COMMAND = "ofti:set"


def read_pipeline_commands(path: Path) -> tuple[list[list[str]], list[str]]:
    commands: list[list[str]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError as exc:
        return [], [f"Failed to read {path.name}: {exc}"]
    header_index = None
    for idx, raw in enumerate(lines):
        if raw.strip() == PIPELINE_HEADER:
            header_index = idx
            break
    if header_index is None:
        return [], [f"Missing {PIPELINE_HEADER} header in {path.name}."]
    for line_no, raw in enumerate(lines[header_index + 1 :], start=header_index + 2):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            errors.append(f"Line {line_no}: {exc}")
            continue
        if not parts:
            continue
        commands.append(parts)
    return commands, errors


def write_pipeline_file(path: Path, commands: Iterable[Iterable[str]]) -> None:
    shebang = "#!/bin/bash"
    if path.is_file():
        try:
            first = path.read_text(errors="ignore").splitlines()[:1]
        except OSError:
            first = []
        if first and first[0].startswith("#!"):
            shebang = first[0].strip()
    lines = [shebang, PIPELINE_HEADER, ""]
    for cmd in commands:
        rendered = " ".join(shlex.quote(part) for part in cmd)
        lines.append(rendered)
    content = "\n".join(lines).rstrip() + "\n"
    path.write_text(content)


def tail_text(text: str, max_lines: int = 20) -> str:
    lines = text.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines) if lines else "(empty)"
    tail = "\n".join(lines[-max_lines:])
    return f"... ({len(lines) - max_lines} lines omitted)\n{tail}"


def run_pipeline_commands(
    case_path: Path,
    commands: Iterable[Iterable[str]],
    *,
    status_cb: Callable[[str], None] | None = None,
) -> list[str]:
    results: list[str] = []
    command_list = [list(cmd) for cmd in commands]
    for idx, cmd in enumerate(command_list, start=1):
        if status_cb is not None:
            status_cb(f"Pipeline {idx}/{len(command_list)}: {' '.join(cmd)}")
        if cmd and cmd[0] == PIPELINE_SET_COMMAND:
            results.extend(_run_pipeline_set(case_path, cmd))
            results.append("")
            continue
        try:
            result = run_trusted(
                cmd,
                cwd=case_path,
                capture_output=True,
                text=True,
                stdin="",
                check=False,
            )
        except OSError as exc:
            results.append(f"$ {' '.join(cmd)}")
            results.append(f"status: ERROR ({exc})")
            break
        status = "OK" if result.returncode == 0 else f"ERROR ({result.returncode})"
        results.append(f"$ {' '.join(cmd)}")
        results.append(f"status: {status}")
        if result.stdout:
            results.append("stdout:")
            results.append(tail_text(result.stdout))
        if result.stderr:
            results.append("stderr:")
            results.append(tail_text(result.stderr))
        results.append("")
        if result.returncode != 0:
            break
    return results


def _run_pipeline_set(case_path: Path, cmd: list[str]) -> list[str]:
    if len(cmd) < 4:
        return [
            f"$ {' '.join(cmd)}",
            "status: ERROR (missing file/key/value)",
        ]
    rel_path = cmd[1]
    key_path = cmd[2].split(".")
    value = " ".join(cmd[3:])
    target = case_path / rel_path
    ok = apply_assignment_or_write(case_path, target, key_path, value)
    status = "OK" if ok else "ERROR"
    return [
        f"$ {' '.join(cmd)}",
        f"status: {status}",
    ]
