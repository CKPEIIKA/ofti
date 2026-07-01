from __future__ import annotations

import contextlib
import importlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


def _load_toml_module() -> Any | None:
    for name in ("tomllib", "tomli"):
        with contextlib.suppress(ModuleNotFoundError):
            return importlib.import_module(name)
    return None


_TOML = _load_toml_module()


@dataclass
class PathDefaults:
    case_root: str | None = None
    queue_root: str | None = None
    bundle_output_dir: str | None = None
    smoke_root: str | None = None
    manifest_root: str | None = None
    snapshot_root: str | None = None
    tmp_root: str | None = None


@dataclass
class RunDefaults:
    default_parallel: int = 0
    poll_interval: float = 0.25
    log_tail_bytes: int = 262144


@dataclass
class QueueDefaults:
    backend: str = "process"
    max_parallel: int = 1
    poll_interval: float = 0.25
    root: str | None = None


@dataclass
class BundleDefaults:
    mesh: str = "auto"
    time: str = "0"
    smoke_iterations: int = 5
    smoke_timeout: str = "60s"
    output_dir: str | None = None


@dataclass
class WatchDefaults:
    poll_interval: float = 0.25
    tail_bytes: int = 262144


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
    example_paths: list[str] = field(default_factory=list)
    paths: PathDefaults = field(default_factory=PathDefaults)
    run: RunDefaults = field(default_factory=RunDefaults)
    queue: QueueDefaults = field(default_factory=QueueDefaults)
    bundle: BundleDefaults = field(default_factory=BundleDefaults)
    watch: WatchDefaults = field(default_factory=WatchDefaults)


_CONFIG: Config | None = None
_CONFIG_TOKEN: tuple[str, str] | None = None


def get_config() -> Config:
    global _CONFIG, _CONFIG_TOKEN
    token = _config_token()
    if _CONFIG is None or token != _CONFIG_TOKEN:
        _CONFIG = _load_config()
        _CONFIG_TOKEN = token
    return _CONFIG


def _config_token() -> tuple[str, str]:
    test_name = os.environ.get("PYTEST_CURRENT_TEST", "")
    return (str(config_path()), test_name)


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
        raw: dict[str, Any] = {}
        if _TOML is not None:
            try:
                parsed = _TOML.loads(path.read_text())
                if isinstance(parsed, dict):
                    raw = cast("dict[str, Any]", parsed)
            except Exception:
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
                cfg.keys[key] = cast("list[str]", value)
    examples_value = raw.get("example_paths")
    if isinstance(examples_value, list):
        example_paths: list[str] = []
        for item in examples_value:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    example_paths.append(stripped)
        cfg.example_paths = example_paths

    _apply_path_defaults(cfg.paths, _section(raw, "paths"))
    _apply_run_defaults(cfg.run, _section(raw, "run"))
    _apply_queue_defaults(cfg.queue, _section(raw, "queue"))
    _apply_bundle_defaults(cfg.bundle, _section(raw, "bundle"))
    _apply_watch_defaults(cfg.watch, _section(raw, "watch"))


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
    env_examples = os.environ.get("OFTI_EXAMPLE_PATHS")
    if env_examples is not None:
        paths = [
            item.strip()
            for item in env_examples.split(os.pathsep)
            if item.strip()
        ]
        cfg.example_paths = paths
    _apply_env_path("OFTI_CASE_ROOT", cfg.paths, "case_root")
    _apply_env_path("OFTI_QUEUE_ROOT", cfg.paths, "queue_root")
    _apply_env_path("OFTI_BUNDLE_OUTPUT_DIR", cfg.paths, "bundle_output_dir")
    _apply_env_path("OFTI_SMOKE_ROOT", cfg.paths, "smoke_root")
    _apply_env_path("OFTI_MANIFEST_ROOT", cfg.paths, "manifest_root")
    _apply_env_path("OFTI_SNAPSHOT_ROOT", cfg.paths, "snapshot_root")
    _apply_env_path("OFTI_TMP_ROOT", cfg.paths, "tmp_root")
    _apply_env_int("OFTI_DEFAULT_PARALLEL", cfg.run, "default_parallel")
    _apply_env_float("OFTI_RUN_POLL_INTERVAL", cfg.run, "poll_interval")
    _apply_env_int("OFTI_LOG_TAIL_BYTES", cfg.run, "log_tail_bytes")
    _apply_env_int("OFTI_QUEUE_MAX_PARALLEL", cfg.queue, "max_parallel")
    _apply_env_float("OFTI_QUEUE_POLL_INTERVAL", cfg.queue, "poll_interval")
    _apply_env_str("OFTI_QUEUE_BACKEND", cfg.queue, "backend")
    _apply_env_path("OFTI_QUEUE_ROOT", cfg.queue, "root")
    _apply_env_str("OFTI_BUNDLE_MESH", cfg.bundle, "mesh")
    _apply_env_str("OFTI_BUNDLE_TIME", cfg.bundle, "time")
    _apply_env_int("OFTI_BUNDLE_SMOKE_ITERATIONS", cfg.bundle, "smoke_iterations")
    _apply_env_str("OFTI_BUNDLE_SMOKE_TIMEOUT", cfg.bundle, "smoke_timeout")
    _apply_env_path("OFTI_BUNDLE_OUTPUT_DIR", cfg.bundle, "output_dir")
    _apply_env_float("OFTI_WATCH_POLL_INTERVAL", cfg.watch, "poll_interval")
    _apply_env_int("OFTI_WATCH_TAIL_BYTES", cfg.watch, "tail_bytes")


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    return value if isinstance(value, dict) else {}


def _string_value(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int_value(raw: dict[str, Any], key: str) -> int | None:
    value = raw.get(key)
    if isinstance(value, int):
        return value
    return None


def _float_value(raw: dict[str, Any], key: str) -> float | None:
    value = raw.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _apply_path_defaults(cfg: PathDefaults, raw: dict[str, Any]) -> None:
    for key in (
        "case_root",
        "queue_root",
        "bundle_output_dir",
        "smoke_root",
        "manifest_root",
        "snapshot_root",
        "tmp_root",
    ):
        if value := _string_value(raw, key):
            setattr(cfg, key, value)


def _apply_run_defaults(cfg: RunDefaults, raw: dict[str, Any]) -> None:
    if (value := _int_value(raw, "default_parallel")) is not None:
        cfg.default_parallel = max(0, value)
    if (value := _float_value(raw, "poll_interval")) is not None:
        cfg.poll_interval = max(0.05, value)
    if (value := _int_value(raw, "log_tail_bytes")) is not None:
        cfg.log_tail_bytes = max(0, value)


def _apply_queue_defaults(cfg: QueueDefaults, raw: dict[str, Any]) -> None:
    if value := _string_value(raw, "backend"):
        cfg.backend = value
    if (value := _int_value(raw, "max_parallel")) is not None:
        cfg.max_parallel = max(1, value)
    if (value := _float_value(raw, "poll_interval")) is not None:
        cfg.poll_interval = max(0.05, value)
    if value := _string_value(raw, "root"):
        cfg.root = value


def _apply_bundle_defaults(cfg: BundleDefaults, raw: dict[str, Any]) -> None:
    if value := _string_value(raw, "mesh"):
        cfg.mesh = value
    if value := _string_value(raw, "time"):
        cfg.time = value
    if (value := _int_value(raw, "smoke_iterations")) is not None:
        cfg.smoke_iterations = max(1, value)
    if value := _string_value(raw, "smoke_timeout"):
        cfg.smoke_timeout = value
    if value := _string_value(raw, "output_dir"):
        cfg.output_dir = value


def _apply_watch_defaults(cfg: WatchDefaults, raw: dict[str, Any]) -> None:
    if (value := _float_value(raw, "poll_interval")) is not None:
        cfg.poll_interval = max(0.05, value)
    if (value := _int_value(raw, "tail_bytes")) is not None:
        cfg.tail_bytes = max(0, value)


def _apply_env_str(name: str, target: object, attr: str) -> None:
    value = os.environ.get(name)
    if value and value.strip():
        setattr(target, attr, value.strip())


def _apply_env_path(name: str, target: object, attr: str) -> None:
    _apply_env_str(name, target, attr)


def _apply_env_int(name: str, target: object, attr: str) -> None:
    value = os.environ.get(name)
    if value:
        with contextlib.suppress(ValueError):
            setattr(target, attr, int(value.strip()))


def _apply_env_float(name: str, target: object, attr: str) -> None:
    value = os.environ.get(name)
    if value:
        with contextlib.suppress(ValueError):
            setattr(target, attr, float(value.strip()))
