from unittest import mock

from ofti.foam import openfoam_env


def test_detect_openfoam_version_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("WM_PROJECT_VERSION", "v999")
    monkeypatch.delenv("FOAM_VERSION", raising=False)
    with mock.patch.object(openfoam_env, "run_trusted") as run_trusted:
        assert openfoam_env.detect_openfoam_version() == "v999"
        run_trusted.assert_not_called()


def test_detect_openfoam_version_uses_foam_version_env(monkeypatch) -> None:
    monkeypatch.delenv("WM_PROJECT_VERSION", raising=False)
    monkeypatch.setenv("FOAM_VERSION", "v123")
    with mock.patch.object(openfoam_env, "run_trusted") as run_trusted:
        assert openfoam_env.detect_openfoam_version() == "v123"
        run_trusted.assert_not_called()


def test_detect_openfoam_version_falls_back_to_unknown(monkeypatch) -> None:
    monkeypatch.delenv("WM_PROJECT_VERSION", raising=False)
    monkeypatch.delenv("FOAM_VERSION", raising=False)
    with mock.patch.object(openfoam_env, "run_trusted", side_effect=OSError):
        assert openfoam_env.detect_openfoam_version() == "unknown"
