from of_tui.editor import autoformat_value


def test_autoformat_single_line_trims_edges_only() -> None:
    assert autoformat_value("  1000;  ") == "1000;"
    assert autoformat_value("preMij    0.014;   ") == "preMij    0.014;"


def test_autoformat_multiline_preserves_inner_whitespace() -> None:
    text = "line1  x;\n  line2    y;\n"
    assert autoformat_value(text) == "line1  x;\n  line2    y;"
