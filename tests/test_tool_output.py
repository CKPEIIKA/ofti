from ofti.core.tool_output import CommandResult, format_command_result, format_log_blob


def test_format_command_result_includes_hint_and_empty_streams() -> None:
    result = CommandResult(returncode=1, stdout="", stderr="")
    summary = format_command_result(["$ cmd"], result, hint="hint")
    assert "status: ERROR" in summary
    assert "hint" in summary
    assert "stdout:\n(empty)" in summary
    assert "stderr:\n(empty)" in summary


def test_format_log_blob_formats_streams() -> None:
    text = format_log_blob("out", "err")
    assert text.startswith("stdout:")
    assert "out" in text
    assert "stderr:" in text
    assert "err" in text
