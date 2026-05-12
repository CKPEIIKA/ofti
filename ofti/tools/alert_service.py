from __future__ import annotations

from typing import Any


def overview_alert_cards(
    *,
    preflight: dict[str, Any] | None = None,
    doctor: dict[str, Any] | None = None,
    status: dict[str, Any] | None = None,
    current: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    residuals: dict[str, Any] | None = None,
) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    _add_preflight_alerts(cards, preflight or {})
    _add_doctor_alerts(cards, doctor or {})
    _add_status_alerts(cards, status or {})
    _add_current_alerts(cards, current or {})
    _add_metric_alerts(cards, metrics or {})
    _add_residual_alerts(cards, residuals or {})
    return cards


def _add_preflight_alerts(cards: list[dict[str, object]], payload: dict[str, Any]) -> None:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    missing = [key for key, ok in checks.items() if not ok]
    if payload.get("solver_error") or missing or payload.get("ok") is False:
        cards.append(
            _card(
                "CRIT",
                "Preflight failed",
                payload.get("solver_error") or ", ".join(missing) or "one or more checks failed",
                "Fix the missing case prerequisites before launch.",
                "knife preflight",
            ),
        )


def _add_doctor_alerts(cards: list[dict[str, object]], payload: dict[str, Any]) -> None:
    errors = list(payload.get("errors", []))
    warnings = list(payload.get("warnings", []))
    if errors:
        cards.append(
            _card(
                "CRIT",
                "Case doctor errors",
                _sample(errors),
                "Open the case doctor report.",
                "knife doctor",
            ),
        )
    if warnings:
        cards.append(
            _card(
                "WARN",
                "Case doctor warnings",
                _sample(warnings),
                "Review warnings before launch.",
                "knife doctor",
            ),
        )


def _add_status_alerts(cards: list[dict[str, object]], payload: dict[str, Any]) -> None:
    if payload.get("solver_error"):
        cards.append(
            _card(
                "CRIT",
                "Solver unresolved",
                payload.get("solver_error"),
                "Check system/controlDict application.",
                "knife status",
            ),
        )
    if payload.get("running") and payload.get("log_fresh") is False:
        cards.append(
            _card(
                "WARN",
                "Solver log looks stale",
                payload.get("log_path") or "log freshness check failed",
                "Inspect live process and log path.",
                "knife status",
            ),
        )
    rtc = (
        payload.get("run_time_control")
        if isinstance(payload.get("run_time_control"), dict)
        else {}
    )
    failed = int(rtc.get("failed") or 0)
    if failed:
        cards.append(
            _card(
                "WARN",
                "Runtime criteria failing",
                f"failed={failed}",
                "Open criteria table and inspect unmet rows.",
                "knife criteria",
            ),
        )
    if payload.get("proc_access_warning"):
        cards.append(
            _card(
                "WARN",
                "Process scan limited",
                payload.get("proc_access_warning"),
                "Live process discovery may be incomplete.",
                "knife status",
            ),
        )


def _add_current_alerts(cards: list[dict[str, object]], payload: dict[str, Any]) -> None:
    if payload.get("proc_access_warning"):
        cards.append(
            _card(
                "WARN",
                "Current process scan limited",
                payload.get("proc_access_warning"),
                "Tracked and untracked process lists may be incomplete.",
                "knife current",
            ),
        )


def _add_metric_alerts(cards: list[dict[str, object]], payload: dict[str, Any]) -> None:
    courant = payload.get("courant") if isinstance(payload.get("courant"), dict) else {}
    co_max = courant.get("max")
    if isinstance(co_max, (int, float)) and co_max > 1.0:
        cards.append(
            _card(
                "WARN",
                "High Courant number",
                f"CoMax={co_max:.6g}",
                "Consider reducing deltaT or enabling adjustable time step.",
                "plot metrics",
            ),
        )


def _add_residual_alerts(cards: list[dict[str, object]], payload: dict[str, Any]) -> None:
    fields = list(payload.get("fields", []))
    if payload and not fields:
        cards.append(
            _card(
                "INFO",
                "No residuals parsed",
                payload.get("log") or "solver log",
                "Confirm solver output format or selected log.",
                "plot residuals",
            ),
        )


def _card(
    severity: str,
    title: str,
    evidence: object,
    action: str,
    source: str,
) -> dict[str, object]:
    return {
        "severity": severity,
        "title": title,
        "evidence": str(evidence),
        "action": action,
        "source": source,
    }


def _sample(items: list[object]) -> str:
    head = "; ".join(str(item) for item in items[:3])
    if len(items) > 3:
        return f"{head}; +{len(items) - 3} more"
    return head
