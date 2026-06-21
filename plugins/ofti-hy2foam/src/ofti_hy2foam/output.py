"""Shared output handling for hy2Foam plugin commands.

Mirrors the core CLI contract: ``--json`` emits a stamped machine payload,
``--table`` emits aligned human output, the two are mutually exclusive (exit 2),
and the default is concise text. Exit code is 0 on success, 1 on a failed check.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from ofti.core.output_contract import command_name, stamp_payload

PayloadLines = Callable[[dict[str, Any]], list[str]]


def emit_payload(
    args: Any,
    payload: dict[str, Any],
    *,
    text_lines: PayloadLines,
    table_lines: PayloadLines | None = None,
    ok_key: str = "ok",
) -> int:
    json_mode = bool(getattr(args, "json", False))
    table_mode = bool(getattr(args, "table", False))
    if json_mode and table_mode:
        print("error: --json and --table are mutually exclusive", file=sys.stderr)
        return 2
    if json_mode:
        print(json.dumps(stamp_payload(payload, command_name(args)), indent=2, sort_keys=True))
    elif table_mode and table_lines is not None:
        print("\n".join(table_lines(payload)))
    else:
        print("\n".join(text_lines(payload)))
    return 0 if payload.get(ok_key, True) else 1
