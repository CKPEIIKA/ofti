from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ofti.core.case_fingerprint import case_fingerprint
from ofti.core.plot import block_bar, sparkline
from ofti.tools import knife_service, plot_service, table_render_service
from ofti.tools.alert_service import overview_alert_cards
from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import plot as plot_ops
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.cli_tools import watch as watch_ops
from ofti.tools.lint_service import lint_payload
from ofti.tools.log_fold_service import fold_log_lines
from ofti.tools.mesh_radar_service import mesh_radar_payload
from ofti.tools.resource_watch_service import resource_watch_payload

OVERVIEW_TAIL_BYTES = 64 * 1024
_DEFAULT_TAIL_BYTES = OVERVIEW_TAIL_BYTES


def captains_deck_payload(
    case_path: Path,
    *,
    tail_bytes: int = _DEFAULT_TAIL_BYTES,
) -> dict[str, Any]:
    return {
        "case": str(case_path),
        "case_dna": case_dna_payload(case_path, tail_bytes=tail_bytes),
        "scopes": mission_scope_payload(case_path),
        "mesh_radar": mesh_radar_payload(case_path),
        "resource_watch": resource_watch_payload(case_path),
    }


def case_dna_payload(case_path: Path, *, tail_bytes: int = _DEFAULT_TAIL_BYTES) -> dict[str, Any]:
    preflight = knife_service.preflight_payload(case_path)
    status = knife_service.status_payload(case_path, lightweight=True, tail_bytes=tail_bytes)
    metrics = _safe_metrics_payload(case_path)
    try:
        initials = knife_service.initials_payload(case_path)
    except (OSError, RuntimeError, ValueError):
        initials = {}
    rtc = status.get("run_time_control") if isinstance(status.get("run_time_control"), dict) else {}
    failed = int(rtc.get("failed", 0)) if isinstance(rtc, dict) else 0
    residual_fields = list(metrics.get("residual_fields", []))
    risk = "low"
    if not preflight.get("ok") or status.get("solver_error"):
        risk = "high"
    elif failed or not residual_fields:
        risk = "medium"
    return {
        "case": str(case_path),
        "solver": status.get("solver_error") or status.get("solver") or preflight.get("solver"),
        "running": status.get("running"),
        "latest_time": status.get("latest_time"),
        "latest_iteration": status.get("latest_iteration"),
        "fields": initials.get("field_count"),
        "patches": initials.get("patch_count"),
        "residual_fields": residual_fields,
        "jobs_running": status.get("jobs_running"),
        "criteria_failed": failed,
        "risk": risk,
        "fingerprint": case_fingerprint(case_path),
    }


def mission_scope_payload(case_path: Path) -> dict[str, Any]:
    metrics, residuals = _safe_log_summary(case_path)
    rows: list[dict[str, object]] = []
    error = metrics.get("error")
    if error:
        return {"rows": [{"scope": "Log metrics", "value": "unavailable", "plot": error}]}

    courant = metrics.get("courant") if isinstance(metrics.get("courant"), dict) else {}
    co_max = _as_float(courant.get("max") if isinstance(courant, dict) else None)
    rows.append(
        {
            "scope": "Courant max",
            "value": co_max,
            "plot": block_bar(co_max, maximum=max(co_max or 0.0, 1.0), width=16),
        },
    )

    execution_value = metrics.get("execution_time")
    execution = execution_value if isinstance(execution_value, dict) else {}
    if isinstance(execution, dict):
        values = [
            _as_float(execution.get("delta_min")),
            _as_float(execution.get("delta_avg")),
            _as_float(execution.get("delta_max")),
        ]
        rows.append(
            {
                "scope": "Sec/iter",
                "value": execution.get("delta_avg"),
                "plot": sparkline(values, width=12),
            },
        )

    for field in list(residuals.get("fields", []))[:8]:
        field_dict = field if isinstance(field, dict) else {}
        values = [
            _as_float(field_dict.get("max")),
            _as_float(field_dict.get("last")),
            _as_float(field_dict.get("min")),
        ]
        rows.append(
            {
                "scope": f"Residual {field_dict.get('field', '?')}",
                "value": field_dict.get("last"),
                "plot": sparkline(values, width=12),
            },
        )
    return {"rows": rows}


@dataclass(frozen=True)
class CaptainsDeckDeps:
    case_dna_payload: Callable[..., dict[str, Any]] = case_dna_payload
    mission_scope_payload: Callable[[Path], dict[str, Any]] = mission_scope_payload
    lint_payload: Callable[[Path], dict[str, Any]] = lint_payload
    mesh_radar_payload: Callable[[Path], dict[str, Any]] = mesh_radar_payload
    resource_watch_payload: Callable[[Path], dict[str, Any]] = resource_watch_payload


class CaptainsDeckData:
    def __init__(self, case_path: Path, *, deps: CaptainsDeckDeps | None = None) -> None:
        self.case_path = case_path
        self.deps = deps or CaptainsDeckDeps()
        self._cache: dict[str, object] = {}

    def _get(self, key: str, build: Callable[[], object]) -> object:
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    def preflight_payload(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._get("preflight", lambda: knife_ops.preflight_payload(self.case_path)),
        )

    def doctor_payload(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._get("doctor", lambda: knife_ops.doctor_payload(self.case_path)),
        )

    def status_payload(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._get(
                "status",
                lambda: knife_ops.status_payload(
                    self.case_path,
                    lightweight=True,
                    tail_bytes=OVERVIEW_TAIL_BYTES,
                ),
            ),
        )

    def current_payload(self) -> dict[str, Any]:
        def build() -> object:
            try:
                return knife_ops.current_payload(self.case_path, live=True)
            except TypeError:
                return knife_ops.current_payload(self.case_path)

        return cast(dict[str, Any], self._get("current", build))

    def log_summary_payload(self) -> dict[str, Any] | None:
        def build() -> object:
            try:
                return plot_ops.log_summary_payload(self.case_path, residual_limit=20)
            except (AttributeError, OSError, RuntimeError, ValueError):
                return None

        return cast(dict[str, Any] | None, self._get("log_summary", build))

    def metrics_payload(self) -> dict[str, Any]:
        summary = self.log_summary_payload()
        if isinstance(summary, dict) and isinstance(summary.get("metrics"), dict):
            return cast(dict[str, Any], summary["metrics"])
        return cast(
            dict[str, Any],
            self._get("metrics", lambda: plot_ops.metrics_payload(self.case_path)),
        )

    def residuals_payload(self) -> dict[str, Any]:
        summary = self.log_summary_payload()
        if isinstance(summary, dict) and isinstance(summary.get("residuals"), dict):
            return cast(dict[str, Any], summary["residuals"])
        return cast(
            dict[str, Any],
            self._get("residuals", lambda: plot_ops.residuals_payload(self.case_path, limit=20)),
        )

    def case_dna_lines(self) -> list[str]:
        return table_render_service.case_dna_table_lines(
            self.deps.case_dna_payload(self.case_path, tail_bytes=OVERVIEW_TAIL_BYTES),
        )

    def scope_lines(self) -> list[str]:
        return table_render_service.scope_table_lines(
            self.deps.mission_scope_payload(self.case_path),
        )

    def mesh_radar_lines(self) -> list[str]:
        return table_render_service.mesh_radar_table_lines(
            self.deps.mesh_radar_payload(self.case_path),
        )

    def resource_watch_lines(self) -> list[str]:
        return table_render_service.resource_watch_table_lines(
            self.deps.resource_watch_payload(self.case_path),
        )

    def preflight_lines(self) -> list[str]:
        return table_render_service.preflight_table_lines(self.preflight_payload())

    def doctor_lines(self) -> list[str]:
        return table_render_service.doctor_table_lines(self.doctor_payload())

    def lint_lines(self) -> list[str]:
        return table_render_service.lint_table_lines(self.deps.lint_payload(self.case_path))

    def status_lines(self) -> list[str]:
        return table_render_service.status_table_lines(self.status_payload())

    def current_lines(self) -> list[str]:
        return table_render_service.current_table_lines(self.current_payload())

    def alert_lines(self) -> list[str]:
        cards = overview_alert_cards(
            preflight=self.preflight_payload(),
            doctor=self.doctor_payload(),
            status=self.status_payload(),
            current=self.current_payload(),
            metrics=self.metrics_payload(),
            residuals=self.residuals_payload(),
        )
        return table_render_service.alert_cards_table_lines(cast(list[object], cards))

    def live_cases_lines(self) -> list[str]:
        payload = self._get(
            "live_cases",
            lambda: run_ops.status_set_payload(
                set_dir=self.case_path.parent,
                explicit_cases=[],
                case_glob="*",
                summary_csv=None,
                lightweight=True,
                tail_bytes=OVERVIEW_TAIL_BYTES,
            ),
        )
        return table_render_service.live_cases_table_lines(payload)  # type: ignore[arg-type]

    def eta_lines(self) -> list[str]:
        payload = self._get(
            "eta",
            lambda: knife_ops.eta_payload(
                self.case_path,
                mode="auto",
                lightweight=True,
                tail_bytes=OVERVIEW_TAIL_BYTES,
            ),
        )
        return table_render_service.eta_table_lines(payload)  # type: ignore[arg-type]

    def log_metrics_lines(self) -> list[str]:
        return table_render_service.metrics_table_lines(self.metrics_payload())

    def residual_lines(self) -> list[str]:
        payload = self.residuals_payload()
        fields = list(payload.get("fields", []))
        lines = table_render_service.residual_payload_table_lines(payload)
        if not fields:
            lines.append("No residuals found.")
        return lines

    def log_residual_split_lines(self) -> list[str]:
        return split_columns(
            "Log metrics",
            self.log_metrics_lines(),
            "Residuals",
            self.residual_lines(),
        )

    def folded_log_lines(self) -> list[str]:
        payload = watch_ops.log_tail_payload(self.case_path, lines=80)
        folded = fold_log_lines(list(payload.get("lines", [])))
        return table_render_service.folded_log_table_lines(
            {"log": payload.get("log"), "rows": folded},
        )

    def panel_lines(self, panel: str) -> list[str]:
        producers: dict[str, Callable[[], list[str]]] = {
            "Flight": self.status_lines,
            "Mission scopes": self.scope_lines,
            "Alerts": self.alert_lines,
            "Live cases": self.live_cases_lines,
            "Case lint": self.lint_lines,
            "Mesh radar": self.mesh_radar_lines,
            "Resource watch": self.resource_watch_lines,
            "Log radar": self.log_residual_split_lines,
        }
        return safe_lines(producers.get(panel, lambda: ["unknown panel"]))


def split_columns(
    left_title: str,
    left_lines: list[str],
    right_title: str,
    right_lines: list[str],
) -> list[str]:
    left = [left_title, "-" * len(left_title), *left_lines]
    right = [right_title, "-" * len(right_title), *right_lines]
    width = min(max((len(line) for line in left), default=0), 72)
    count = max(len(left), len(right))
    rows: list[str] = []
    for index in range(count):
        left_text = left[index] if index < len(left) else ""
        right_text = right[index] if index < len(right) else ""
        rows.append(f"{left_text[:width]:<{width}} | {right_text}")
    return rows


def safe_lines(build_lines: Callable[[], list[str]]) -> list[str]:
    try:
        return list(build_lines())
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        return [f"unavailable: {exc}"]


def _safe_log_summary(case_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        summary = plot_service.log_summary_payload(case_path, residual_limit=20)
    except (AttributeError, OSError, RuntimeError, ValueError):
        return _safe_metrics_payload(case_path), _safe_residuals_payload(case_path)
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    residuals = summary.get("residuals") if isinstance(summary.get("residuals"), dict) else {}
    return metrics, residuals


def _safe_metrics_payload(case_path: Path) -> dict[str, Any]:
    try:
        return plot_service.metrics_payload(case_path)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"residual_fields": [], "error": str(exc)}


def _safe_residuals_payload(case_path: Path) -> dict[str, Any]:
    try:
        return plot_service.residuals_payload(case_path, limit=20)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"fields": [], "error": str(exc)}


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
