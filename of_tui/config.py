from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, cast
import os
import shutil
import tomllib


@dataclass
class Config:
    fzf: str = "auto"
    use_runfunctions: bool = True
    use_cleanfunctions: bool = True
    colors: Dict[str, str] = field(
        default_factory=lambda: {"focus_fg": "black", "focus_bg": "cyan"}
    )
    keys: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "up": ["k"],
            "down": ["j"],
            "select": ["l", "\n"],
            "back": ["h", "q"],
            "help": ["?"],
            "command": [":"],
            "search": ["/"],
            "top": ["g"],
            "bottom": ["G"],
        }
    )


_CONFIG: Optional[Config] = None


def get_config() -> Config:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = _load_config()
    return _CONFIG


def config_path() -> Path:
    override = os.environ.get("OF_TUI_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path("~/.config/of_tui/config.toml").expanduser()


def fzf_enabled() -> bool:
    cfg = get_config()
    if cfg.fzf == "off":
        return False
    if cfg.fzf == "on":
        return shutil.which("fzf") is not None
    return shutil.which("fzf") is not None


def key_in(key: int, labels: List[str]) -> bool:
    for label in labels:
        if not label:
            continue
        if label == "\n":
            if key in (10, 13):
                return True
            continue
        if len(label) == 1 and key == ord(label):
            return True
    return False


def _load_config() -> Config:
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


def _apply_file_config(cfg: Config, raw: Dict[str, Any]) -> None:
    fzf_value = raw.get("fzf")
    if isinstance(fzf_value, str):
        cfg.fzf = fzf_value.strip().lower()

    run_value = raw.get("use_runfunctions")
    if isinstance(run_value, bool):
        cfg.use_runfunctions = run_value

    clean_value = raw.get("use_cleanfunctions")
    if isinstance(clean_value, bool):
        cfg.use_cleanfunctions = clean_value

    colors = raw.get("colors")
    if isinstance(colors, dict):
        for key in ("focus_fg", "focus_bg"):
            value = colors.get(key)
            if isinstance(value, str):
                cfg.colors[key] = value.strip().lower()

    keys = raw.get("keys")
    if isinstance(keys, dict):
        for key, value in keys.items():
            if isinstance(key, str) and isinstance(value, list):
                if all(isinstance(item, str) for item in value):
                    cfg.keys[key] = cast(List[str], value)


def _apply_env_overrides(cfg: Config) -> None:
    env_fzf = os.environ.get("OF_TUI_FZF")
    if env_fzf:
        cfg.fzf = env_fzf.strip().lower()

    env_run = os.environ.get("OF_TUI_USE_RUNFUNCTIONS")
    if env_run is not None:
        cfg.use_runfunctions = env_run.strip() in ("1", "true", "yes", "on")

    env_clean = os.environ.get("OF_TUI_USE_CLEANFUNCTIONS")
    if env_clean is not None:
        cfg.use_cleanfunctions = env_clean.strip() in ("1", "true", "yes", "on")
