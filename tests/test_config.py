"""Config loader and helpers."""

from __future__ import annotations

from pathlib import Path

from ofti.foam import config


def _reset_config() -> None:
    config._CONFIG = None


def test_config_path_env_override(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "cfg.toml"
    monkeypatch.setenv("OFTI_CONFIG", str(override))
    _reset_config()

    assert config.config_path() == override


def test_key_in_handles_basic_keys() -> None:
    assert config.key_in(ord("k"), ["k"]) is True
    assert config.key_in(10, ["\n"]) is True
    assert config.key_in(ord("x"), ["k"]) is False


def test_fzf_enabled_respects_env(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "cfg.toml"
    cfg.write_text('fzf = "off"\n')
    monkeypatch.setenv("OFTI_CONFIG", str(cfg))
    _reset_config()

    assert config.fzf_enabled() is False

    monkeypatch.setenv("OFTI_FZF", "on")
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
                "[paths]",
                'case_root = "~/OpenFOAM"',
                'queue_root = "/scratch/ofti-queues"',
                'bundle_output_dir = "/scratch/bundles"',
                'smoke_root = "/scratch/smoke"',
                'manifest_root = "/scratch/manifests"',
                'snapshot_root = "/scratch/snapshots"',
                'tmp_root = "/scratch/tmp"',
                "",
                "[run]",
                "default_parallel = 4",
                "poll_interval = 0.5",
                "log_tail_bytes = 4096",
                "",
                "[queue]",
                'backend = "foamlib-async"',
                "max_parallel = 3",
                "poll_interval = 0.75",
                'root = "/scratch/queue-root"',
                "",
                "[bundle]",
                'mesh = "include-polyMesh"',
                'time = "latest"',
                "smoke_iterations = 7",
                'smoke_timeout = "90s"',
                'output_dir = "/scratch/bundle-output"',
                "",
                "[watch]",
                "poll_interval = 1.25",
                "tail_bytes = 8192",
                "",
                "[keys]",
                'up = ["w"]',
                'down = ["s"]',
            ],
        ),
    )
    monkeypatch.setenv("OFTI_CONFIG", str(cfg))
    monkeypatch.setenv("OFTI_USE_CLEANFUNCTIONS", "0")
    _reset_config()

    cfg_obj = config.get_config()
    assert cfg_obj.fzf == "off"
    assert cfg_obj.use_runfunctions is False
    assert cfg_obj.use_cleanfunctions is False
    assert cfg_obj.colors["focus_fg"] == "red"
    assert cfg_obj.colors["focus_bg"] == "blue"
    assert cfg_obj.keys["up"] == ["w"]
    assert cfg_obj.paths.case_root == "~/OpenFOAM"
    assert cfg_obj.paths.queue_root == "/scratch/ofti-queues"
    assert cfg_obj.paths.bundle_output_dir == "/scratch/bundles"
    assert cfg_obj.paths.smoke_root == "/scratch/smoke"
    assert cfg_obj.paths.manifest_root == "/scratch/manifests"
    assert cfg_obj.paths.snapshot_root == "/scratch/snapshots"
    assert cfg_obj.paths.tmp_root == "/scratch/tmp"
    assert cfg_obj.run.default_parallel == 4
    assert cfg_obj.run.poll_interval == 0.5
    assert cfg_obj.run.log_tail_bytes == 4096
    assert cfg_obj.queue.backend == "foamlib-async"
    assert cfg_obj.queue.max_parallel == 3
    assert cfg_obj.queue.poll_interval == 0.75
    assert cfg_obj.queue.root == "/scratch/queue-root"
    assert cfg_obj.bundle.mesh == "include-polyMesh"
    assert cfg_obj.bundle.time == "latest"
    assert cfg_obj.bundle.smoke_iterations == 7
    assert cfg_obj.bundle.smoke_timeout == "90s"
    assert cfg_obj.bundle.output_dir == "/scratch/bundle-output"
    assert cfg_obj.watch.poll_interval == 1.25
    assert cfg_obj.watch.tail_bytes == 8192


def test_global_config_env_overrides(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "cfg.toml"
    cfg.write_text("[run]\ndefault_parallel = 2\n")
    monkeypatch.setenv("OFTI_CONFIG", str(cfg))
    monkeypatch.setenv("OFTI_CASE_ROOT", "/cases")
    monkeypatch.setenv("OFTI_QUEUE_ROOT", "/queues")
    monkeypatch.setenv("OFTI_DEFAULT_PARALLEL", "8")
    monkeypatch.setenv("OFTI_QUEUE_MAX_PARALLEL", "4")
    monkeypatch.setenv("OFTI_BUNDLE_MESH", "exclude")
    _reset_config()

    cfg_obj = config.get_config()
    assert cfg_obj.paths.case_root == "/cases"
    assert cfg_obj.paths.queue_root == "/queues"
    assert cfg_obj.queue.root == "/queues"
    assert cfg_obj.run.default_parallel == 8
    assert cfg_obj.queue.max_parallel == 4
    assert cfg_obj.bundle.mesh == "exclude"
