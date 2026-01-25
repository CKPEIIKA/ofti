from __future__ import annotations

import contextlib
import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


@dataclass
class Config:
    fzf: str = "auto"
    use_runfunctions: bool = True
    use_cleanfunctions: bool = True
    enable_entry_cache: bool = True
    enable_background_checks: bool = True
    enable_background_entry_crawl: bool = False
    validate_on_save: bool = False
    openfoam_bashrc: str | None = None
    courant_limit: float = 1.0
    colors: dict[str, str] = field(
        default_factory=lambda: {"focus_fg": "black", "focus_bg": "cyan"},
    )
    keys: dict[str, list[str]] = field(
        default_factory=lambda: {
            "up": ["k"],
            "down": ["j"],
            "select": ["l", "\n"],
            "back": ["h", "ESC"],
            "quit": ["q"],
            "help": ["?"],
            "command": [":"],
            "search": ["/"],
            "global_search": ["s"],
            "top": ["g"],
            "bottom": ["G"],
            "view": ["v"],
        },
    )


_CONFIG: Config | None = None


def get_config() -> Config:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = _load_config()
    return _CONFIG


def config_path() -> Path:
    override = os.environ.get("OFTI_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path("~/.config/ofti/config.toml").expanduser()


def fzf_enabled() -> bool:
    cfg = get_config()
    if cfg.fzf == "off":
        return False
    if cfg.fzf == "on":
        return shutil.which("fzf") is not None
    return shutil.which("fzf") is not None


def key_in(key: int, labels: list[str]) -> bool:
    for label in labels:
        if not label:
            continue
        if label.upper() == "ESC":
            if key == 27:
                return True
            continue
        if label == "\n":
            if key in (10, 13):
                return True
            continue
        if len(label) == 1 and key == ord(label):
            return True
    return False


def key_labels(labels: list[str]) -> str:
    display: list[str] = []
    for label in labels:
        if label.upper() == "ESC":
            display.append("Esc")
        elif label == "\n":
            display.append("Enter")
        elif label:
            display.append(label)
    return "/".join(display)


def key_hint(name: str, fallback: str = "") -> str:
    cfg = get_config()
    labels = cfg.keys.get(name, [])
    return key_labels(labels) if labels else fallback


def _load_config() -> Config:
    if os.environ.get("PYTEST_CURRENT_TEST") and "OFTI_CONFIG" not in os.environ:
        return Config()
    cfg = Config()
    path = config_path()
    if path.is_file():
        try:
            raw = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            raw = {}
        _apply_file_config(cfg, raw)

    _apply_env_overrides(cfg)
    return cfg


def _apply_file_config(cfg: Config, raw: dict[str, Any]) -> None:
    fzf_value = raw.get("fzf")
    if isinstance(fzf_value, str):
        cfg.fzf = fzf_value.strip().lower()

    run_value = raw.get("use_runfunctions")
    if isinstance(run_value, bool):
        cfg.use_runfunctions = run_value

    clean_value = raw.get("use_cleanfunctions")
    if isinstance(clean_value, bool):
        cfg.use_cleanfunctions = clean_value

    cache_value = raw.get("enable_entry_cache")
    if isinstance(cache_value, bool):
        cfg.enable_entry_cache = cache_value

    bg_checks_value = raw.get("enable_background_checks")
    if isinstance(bg_checks_value, bool):
        cfg.enable_background_checks = bg_checks_value

    crawl_value = raw.get("enable_background_entry_crawl")
    if isinstance(crawl_value, bool):
        cfg.enable_background_entry_crawl = crawl_value
    bashrc_value = raw.get("openfoam_bashrc")
    if isinstance(bashrc_value, str) and bashrc_value.strip():
        cfg.openfoam_bashrc = bashrc_value.strip()
    courant_value = raw.get("courant_limit")
    if isinstance(courant_value, (int, float)):
        cfg.courant_limit = float(courant_value)

    colors = raw.get("colors")
    if isinstance(colors, dict):
        for key in ("focus_fg", "focus_bg"):
            value = colors.get(key)
            if isinstance(value, str):
                cfg.colors[key] = value.strip().lower()

    keys = raw.get("keys")
    if isinstance(keys, dict):
        for key, value in keys.items():
            if (
                isinstance(key, str)
                and isinstance(value, list)
                and all(isinstance(item, str) for item in value)
            ):
                cfg.keys[key] = cast(list[str], value)


def _apply_env_overrides(cfg: Config) -> None:
    env_fzf = os.environ.get("OFTI_FZF")
    if env_fzf:
        cfg.fzf = env_fzf.strip().lower()

    env_run = os.environ.get("OFTI_USE_RUNFUNCTIONS")
    if env_run is not None:
        cfg.use_runfunctions = env_run.strip() in ("1", "true", "yes", "on")

    env_clean = os.environ.get("OFTI_USE_CLEANFUNCTIONS")
    if env_clean is not None:
        cfg.use_cleanfunctions = env_clean.strip() in ("1", "true", "yes", "on")

    env_cache = os.environ.get("OFTI_ENABLE_ENTRY_CACHE")
    if env_cache is not None:
        cfg.enable_entry_cache = env_cache.strip() in ("1", "true", "yes", "on")

    env_bg = os.environ.get("OFTI_ENABLE_BACKGROUND_CHECKS")
    if env_bg is not None:
        cfg.enable_background_checks = env_bg.strip() in ("1", "true", "yes", "on")

    env_crawl = os.environ.get("OFTI_ENABLE_BACKGROUND_ENTRY_CRAWL")
    if env_crawl is not None:
        cfg.enable_background_entry_crawl = env_crawl.strip() in ("1", "true", "yes", "on")
    env_bashrc = os.environ.get("OFTI_BASHRC")
    if env_bashrc:
        cfg.openfoam_bashrc = env_bashrc.strip()
    env_courant = os.environ.get("OFTI_COURANT_LIMIT")
    if env_courant:
        with contextlib.suppress(ValueError):
            cfg.courant_limit = float(env_courant.strip())
