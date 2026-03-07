from __future__ import annotations

import os
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class _RunTrustedResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


class _PopenResult(Protocol):
    pid: int


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    pid: int | None = None
    log_path: Path | None = None


def execute_case_command(
    case_path: Path,
    name: str,
    cmd: list[str],
    *,
    background: bool,
    detached: bool = True,
    log_path: Path | None = None,
    pid_path: Path | None = None,
    extra_env: dict[str, str] | None = None,
    with_bashrc_fn: Callable[[str], str],
    run_trusted_fn: Callable[..., _RunTrustedResult],
    popen_fn: Callable[..., _PopenResult],
    register_job_fn: Callable[[Path, str, int, str, Path | None], object],
) -> RunResult:
    command_text = " ".join(shlex.quote(part) for part in cmd)
    shell_cmd = with_bashrc_fn(command_text)
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    if extra_env:
        env.update(extra_env)

    if background:
        safe = safe_name(name)
        chosen_log_path = log_path if log_path is not None else Path(f"log.{safe}")
        if not chosen_log_path.is_absolute():
            chosen_log_path = case_path / chosen_log_path
        chosen_log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = chosen_log_path.open("a", encoding="utf-8", errors="ignore")
        process = popen_fn(
            ["/bin/bash", "--noprofile", "--norc", "-c", shell_cmd],
            cwd=case_path,
            stdout=handle,
            stderr=handle,
            text=True,
            env=env,
            start_new_session=detached,
        )
        handle.close()
        process_pid = int(process.pid)
        if pid_path is not None:
            chosen_pid_path = pid_path if pid_path.is_absolute() else case_path / pid_path
            chosen_pid_path.parent.mkdir(parents=True, exist_ok=True)
            chosen_pid_path.write_text(f"{process_pid}\n")
        register_job_fn(case_path, name, process_pid, shell_cmd, chosen_log_path)
        return RunResult(0, "", "", pid=process_pid, log_path=chosen_log_path)

    result = run_trusted_fn(
        ["/bin/bash", "--noprofile", "--norc", "-c", shell_cmd],
        cwd=case_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return RunResult(
        int(result.returncode),
        str(result.stdout),
        str(result.stderr),
    )


def dry_run_command(cmd: list[str], *, with_bashrc_fn: Callable[[str], str]) -> str:
    command_text = " ".join(shlex.quote(part) for part in cmd)
    return with_bashrc_fn(command_text)


def safe_name(value: str) -> str:
    safe = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_", "."})
    return safe or "tool"
