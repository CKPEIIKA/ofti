# ruff: noqa: INP001
from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

PLUGIN_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SRC))

from ofti_hy2foam.compare import _compare_check_table_lines  # noqa: E402
from ofti_hy2foam.output import emit_payload  # noqa: E402
from ofti_hy2foam.preflight import Hy2FoamPreflightCommand, _preflight_table_lines  # noqa: E402

from ofti.app.cli_adapters.command_builder import build_spec_parser  # noqa: E402


def test_emit_payload_rejects_json_and_table(capsys) -> None:
    code = emit_payload(
        SimpleNamespace(json=True, table=True), {"ok": True}, text_lines=lambda _p: ["x"],
    )
    assert code == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_emit_payload_table_mode_renders(capsys) -> None:
    code = emit_payload(
        SimpleNamespace(json=False, table=True),
        {"ok": True},
        text_lines=lambda _p: ["text"],
        table_lines=lambda _p: ["TABLE"],
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "TABLE" in out
    assert "text" not in out


def test_emit_payload_text_default_and_exit_code(capsys) -> None:
    code = emit_payload(
        SimpleNamespace(json=False, table=False), {"ok": False}, text_lines=lambda _p: ["plain"],
    )
    assert code == 1
    assert "plain" in capsys.readouterr().out


def test_preflight_table_lines_has_headers() -> None:
    payload = {
        "case": "/c",
        "ok": False,
        "checks": [{"name": "required_fields", "status": "FAIL", "detail": "missing Tt"}],
    }
    joined = "\n".join(_preflight_table_lines(payload))
    assert "case=/c" in joined
    assert "Check" in joined
    assert "Status" in joined
    assert "Detail" in joined
    assert "required_fields" in joined


def test_compare_check_table_lines_lists_mesh_files() -> None:
    payload = {
        "latest_common_time": "0.1",
        "same_mesh": {
            "same": False,
            "files": [
                {"file": "points", "same": True, "left_present": True, "right_present": True},
                {"file": "owner", "same": False, "left_present": True, "right_present": False},
            ],
        },
    }
    joined = "\n".join(_compare_check_table_lines(payload))
    assert "File" in joined
    assert "points" in joined
    assert "owner" in joined


def test_preflight_table_flag_end_to_end(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "0").mkdir(parents=True)
    (case / "system").mkdir()
    parser = argparse.ArgumentParser()
    build_spec_parser(parser.add_subparsers(), Hy2FoamPreflightCommand().command_spec())

    args = parser.parse_args(["hy2foam-preflight", str(case), "--table"])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = args.func(args)

    assert "Check" in buffer.getvalue()
    assert code in (0, 1)
