from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from os import PathLike


def resolve_executable(cmd: str) -> str:
    if "/" in cmd:
        return cmd
    resolved = shutil.which(cmd)
    if resolved is None:
        raise FileNotFoundError(f"Executable not found: {cmd}")
    return resolved


def run_trusted(
    args: Iterable[str],
    *,
    cwd: str | PathLike[str] | None = None,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    text: bool = True,
    capture_output: bool = True,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    args_list = list(args)
    if not args_list:
        raise ValueError("No command specified")
    args_list[0] = resolve_executable(args_list[0])
    return subprocess.run(  # noqa: S603
        args_list,
        cwd=cwd,
        input=stdin,
        env=env,
        text=text,
        capture_output=capture_output,
        check=check,
    )
