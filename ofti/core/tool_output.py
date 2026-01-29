from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def format_command_result(
    command_lines: list[str],
    result: CommandResult,
    hint: str | None = None,
) -> str:
    status = "OK" if result.returncode == 0 else "ERROR"
    lines = [*command_lines, "", f"status: {status} (exit code {result.returncode})", ""]
    if hint:
        lines.append(hint)
        lines.append("")
    lines += [
        "stdout:",
        result.stdout or "(empty)",
        "",
        "stderr:",
        result.stderr or "(empty)",
    ]
    return "\n".join(lines)


def format_log_blob(stdout: str, stderr: str) -> str:
    return "\n".join(
        [
            "stdout:",
            stdout or "(empty)",
            "",
            "stderr:",
            stderr or "(empty)",
        ],
    )
