from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.plugins import PluginRecord, PluginRegistry, discover_plugins


def list_payload(registry: PluginRegistry | None = None) -> dict[str, Any]:
    selected = registry or discover_plugins()
    plugins = [_plugin_row(record) for record in selected.plugins]
    return {
        "ok": not selected.errors,
        "plugin_count": len(plugins),
        "loaded": sum(row["status"] == "loaded" for row in plugins),
        "failed": sum(row["status"] == "failed" for row in plugins),
        "plugins": plugins,
        "registrations": _registry_surfaces(selected),
        "errors": list(selected.errors),
    }


def doctor_payload(registry: PluginRegistry | None = None) -> dict[str, Any]:
    payload = list_payload(registry)
    warnings = [
        f"{row['name']}: loaded but registered no OFTI surfaces"
        for row in payload["plugins"]
        if row["status"] == "loaded" and not row["registrations"]
    ]
    payload["warnings"] = warnings
    payload["ok"] = not payload["errors"] and not warnings
    return payload


def progress_metrics_payload(
    case_dir: Path,
    *,
    log_path: Path | None = None,
    registry: PluginRegistry | None = None,
) -> dict[str, Any]:
    selected = registry or discover_plugins()
    metrics: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    for name, provider in sorted(selected.progress_metrics.items()):
        try:
            metrics[name] = dict(
                provider.progress_metrics(
                    case_dir,
                    log_path=log_path,
                ),
            )
        except Exception as exc:  # Plugin failures must not hide core progress.
            errors.append(f"{name}: {exc}")
    return {
        "metrics": metrics,
        "errors": errors,
    }


def attach_progress_metrics(
    progress: dict[str, Any],
    case_dir: Path,
    *,
    log_path: Path | None = None,
    registry: PluginRegistry | None = None,
) -> dict[str, Any]:
    plugin_payload = progress_metrics_payload(
        case_dir,
        log_path=log_path,
        registry=registry,
    )
    progress["plugin_metrics"] = plugin_payload["metrics"]
    progress["plugin_metric_errors"] = plugin_payload["errors"]
    return progress


def _plugin_row(record: PluginRecord) -> dict[str, object]:
    return {
        "name": record.name,
        "distribution": record.distribution,
        "version": record.version,
        "entry_point": record.entry_point,
        "status": record.status,
        "registrations": {kind: list(names) for kind, names in sorted(record.registrations.items())},
        "errors": list(record.errors),
    }


def _registry_surfaces(registry: PluginRegistry) -> dict[str, list[str]]:
    return {
        "presets": sorted(registry.presets),
        "physical_profiles": sorted(registry.physical_profiles),
        "knife_commands": sorted(registry.knife_commands),
        "run_commands": sorted(registry.run_commands),
        "watch_commands": sorted(registry.watch_commands),
        "result_commands": sorted(registry.result_commands),
        "progress_metrics": sorted(registry.progress_metrics),
        "bundle_hints": sorted(registry.bundle_hints),
    }
