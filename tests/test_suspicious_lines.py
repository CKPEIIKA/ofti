from ofti.core.syntax import find_suspicious_lines


def test_find_suspicious_lines_flags_missing_semicolon() -> None:
    content = "FoamFile\n{\nstartFrom latestTime\n}\n"
    warnings = find_suspicious_lines(content)
    assert any("missing ';'" in w for w in warnings)


def test_find_suspicious_lines_flags_unexpected_closing_brace() -> None:
    content = "}\n"
    warnings = find_suspicious_lines(content)
    assert any("unexpected '}'" in w for w in warnings)


def test_find_suspicious_lines_flags_unmatched_open_brace() -> None:
    content = "FoamFile\n{\n    version 2.0;\n"
    warnings = find_suspicious_lines(content)
    assert any("unmatched '{'" in w for w in warnings)


def test_find_suspicious_lines_ignores_header_banner() -> None:
    content = (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| Version:  v2312                                                         |\n"
        "| Web:      www.openfoam.com                                              |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "}\n"
    )
    warnings = find_suspicious_lines(content)
    assert warnings == []


def test_find_suspicious_lines_ignore_line_comments() -> None:
    content = "FoamFile\n{\n    // comment explaining version\n    version     2.0;\n}\n"
    warnings = find_suspicious_lines(content)
    assert warnings == []


def test_find_suspicious_lines_ignore_block_comments() -> None:
    content = "FoamFile\n{\n    /*\n       comment block\n    */\n    version     2.0;\n}\n"
    warnings = find_suspicious_lines(content)
    assert warnings == []


def test_find_suspicious_lines_accepts_openfoam_table_lists() -> None:
    content = """\
FoamFile
{
    version 2.0;
}
species
(
    A
    B
);
coeffs
(
    (A B) 1.0 2.0 3.0
    (B A) 4.0 5.0 6.0
);
"""

    assert find_suspicious_lines(content) == []
