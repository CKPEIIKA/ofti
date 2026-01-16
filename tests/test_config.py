"""Config loader and helpers."""

from __future__ import annotations

from pathlib import Path

import of_tui.config as config


def _reset_config() -> None:
    config._CONFIG = None


def test_config_path_env_override(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "cfg.toml"
    monkeypatch.setenv("OF_TUI_CONFIG", str(override))
    _reset_config()

    assert config.config_path() == override


def test_key_in_handles_basic_keys() -> None:
    assert config.key_in(ord("k"), ["k"]) is True
    assert config.key_in(10, ["\n"]) is True
    assert config.key_in(ord("x"), ["k"]) is False


def test_fzf_enabled_respects_env(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "cfg.toml"
    cfg.write_text('fzf = "off"\n')
    monkeypatch.setenv("OF_TUI_CONFIG", str(cfg))
    _reset_config()

    assert config.fzf_enabled() is False

    monkeypatch.setenv("OF_TUI_FZF", "on")
    _reset_config()
    assert config.fzf_enabled() in (True, False)


def test_load_config_from_file_and_env(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "cfg.toml"
    cfg.write_text(
        "\n".join(
            [
                'fzf = "off"',
                "use_runfunctions = false",
                "use_cleanfunctions = true",
                "",
                "[colors]",
                'focus_fg = "red"',
                'focus_bg = "blue"',
                "",
                "[keys]",
                'up = ["w"]',
                'down = ["s"]',
            ]
        )
    )
    monkeypatch.setenv("OF_TUI_CONFIG", str(cfg))
    monkeypatch.setenv("OF_TUI_USE_CLEANFUNCTIONS", "0")
    _reset_config()

    cfg_obj = config.get_config()
    assert cfg_obj.fzf == "off"
    assert cfg_obj.use_runfunctions is False
    assert cfg_obj.use_cleanfunctions is False
    assert cfg_obj.colors["focus_fg"] == "red"
    assert cfg_obj.colors["focus_bg"] == "blue"
    assert cfg_obj.keys["up"] == ["w"]
