from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manpage_source_and_generated_output_cover_public_contract() -> None:
    source = (ROOT / "man" / "ofti.1.scd").read_text()
    generated = (ROOT / "man" / "ofti.1").read_text()

    for section in ("NAME", "SYNOPSIS", "DESCRIPTION", "COMMANDS", "ENVIRONMENT", "FILES", "EXAMPLES"):
        assert f"# {section}" in source
        assert f".SH {section}" in generated
    for command in ("knife", "run", "watch", "plot", "bundle", "unbundle", "result"):
        assert command in source
        assert command in generated
    assert "/home/" not in source
    assert "/home/" not in generated


def test_manpage_scripts_are_user_local_and_reproducible() -> None:
    build = (ROOT / "scripts" / "build_manpage.sh").read_text()
    install = (ROOT / "scripts" / "install_manpage.sh").read_text()

    assert "scdoc <" in build
    assert "mktemp" in build
    assert "sudo" not in install
    assert "XDG_DATA_HOME" in install
    assert ".local/share" in install
