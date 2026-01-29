from pathlib import Path
from unittest import mock

from ofti.foam.openfoam_env import (
    detect_openfoam_version,
    ensure_environment,
    resolve_openfoam_bashrc,
    with_bashrc,
    wm_project_dir_from_bashrc,
)


def test_resolve_openfoam_bashrc_prefers_env(tmp_path: Path, monkeypatch) -> None:
    bashrc = tmp_path / "etc" / "bashrc"
    bashrc.parent.mkdir(parents=True)
    bashrc.write_text("#!/bin/sh\n")
    monkeypatch.setenv("OFTI_BASHRC", str(bashrc))

    resolved = resolve_openfoam_bashrc()
    assert resolved == bashrc


def test_wm_project_dir_from_bashrc(tmp_path: Path) -> None:
    bashrc = tmp_path / "OpenFOAM" / "etc" / "bashrc"
    bashrc.parent.mkdir(parents=True)
    bashrc.write_text("")
    assert wm_project_dir_from_bashrc(bashrc) == str(bashrc.parent.parent)


def test_detect_openfoam_version_from_env(monkeypatch) -> None:
    monkeypatch.setenv("WM_PROJECT_VERSION", "v2406")
    assert detect_openfoam_version() == "v2406"


def test_detect_openfoam_version_from_foamversion(monkeypatch) -> None:
    monkeypatch.delenv("WM_PROJECT_VERSION", raising=False)
    monkeypatch.delenv("FOAM_VERSION", raising=False)
    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "v2306\n"
    completed.stderr = ""
    with mock.patch("ofti.foam.openfoam_env.run_trusted", return_value=completed):
        assert detect_openfoam_version() == "v2306"


def test_ensure_environment(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _cmd: "/usr/bin/foamDictionary")
    ensure_environment()


def test_with_bashrc_injects_marker(tmp_path: Path, monkeypatch) -> None:
    bashrc = tmp_path / "etc" / "bashrc"
    bashrc.parent.mkdir(parents=True)
    bashrc.write_text("")
    monkeypatch.setenv("OFTI_BASHRC", str(bashrc))
    cmd = with_bashrc("echo hi")
    assert str(bashrc) in cmd
