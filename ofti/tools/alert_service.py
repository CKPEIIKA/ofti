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


def overview_alarm_state(cards: list[dict[str, object]]) -> str:
    severities = {str(card.get("severity", "")).upper() for card in cards}
    if "CRIT" in severities:
        return "ABORT"
    if "WARN" in severities:
        return "WARNING"
    if "INFO" in severities:
        return "CAUTION"
    return "NORMAL"


def _add_preflight_alerts(cards: list[dict[str, object]], payload: dict[str, Any]) -> None:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    missing = [key for key, ok in checks.items() if not ok]
    if payload.get("solver_error") or missing or payload.get("ok") is False:
        cards.append(
            _card(
                "CRIT",
                "Preflight failed",
                payload.get("solver_error") or ", ".join(missing) or "one or more checks failed",
                "Launching this case is likely to fail or run the wrong solver.",
                "Fix the missing case prerequisites before launch.",
                "knife preflight",
                _files_from_checks(missing, fallback=["system/controlDict"]),
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
                "The case has structural issues that can invalidate setup or launch.",
                "Open the case doctor report.",
                "knife doctor",
                [],
            ),
        )
    if warnings:
        cards.append(
            _card(
                "WARN",
                "Case doctor warnings",
                _sample(warnings),
                "The case may run, but setup quality or results may be suspect.",
                "Review warnings before launch.",
                "knife doctor",
                [],
            ),
        )


def _add_status_alerts(cards: list[dict[str, object]], payload: dict[str, Any]) -> None:
    if payload.get("solver_error"):
        cards.append(
            _card(
                "CRIT",
                "Solver unresolved",
                payload.get("solver_error"),
                "OFTI cannot reliably launch or monitor the solver command.",
                "Check system/controlDict application.",
                "knife status",
                ["system/controlDict"],
            ),
        )
    if payload.get("running") and payload.get("log_fresh") is False:
        cards.append(
            _card(
                "WARN",
                "Solver log looks stale",
                payload.get("log_path") or "log freshness check failed",
                "Live telemetry may be stale or attached to the wrong run.",
                "Inspect live process and log path.",
                "knife status",
                _path_list(payload.get("log_path")),
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
                "The run is not satisfying configured stop/convergence criteria.",
                "Open criteria table and inspect unmet rows.",
                "knife criteria",
                ["system/controlDict", "system/fvSolution"],
            ),
        )
    if payload.get("proc_access_warning"):
        _add_proc_warning_card(cards, "Process scan limited", payload, "knife status")


def _add_current_alerts(cards: list[dict[str, object]], payload: dict[str, Any]) -> None:
    if payload.get("proc_access_warning"):
        _add_proc_warning_card(cards, "Current process scan limited", payload, "knife current")


def _add_metric_alerts(cards: list[dict[str, object]], payload: dict[str, Any]) -> None:
    courant = payload.get("courant") if isinstance(payload.get("courant"), dict) else {}
    co_max = courant.get("max")
    if isinstance(co_max, (int, float)) and co_max > 1.0:
        cards.append(
            _card(
                "WARN",
                "High Courant number",
                f"CoMax={co_max:.6g}",
                "The solver may become unstable or diverge.",
                "Consider reducing deltaT or enabling adjustable time step.",
                "plot metrics",
                ["system/controlDict"],
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
                "Convergence scopes and residual-based alerts are unavailable.",
                "Confirm solver output format or selected log.",
                "plot residuals",
                _path_list(payload.get("log")),
            ),
        )


def _card(
    severity: str,
    title: str,
    evidence: object,
    impact: str,
    action: str,
    source: str,
    files: list[str],
) -> dict[str, object]:
    open_target = files[0] if files else "-"
    return {
        "severity": severity,
        "title": title,
        "impact": impact,
        "evidence": str(evidence),
        "action": action,
        "source": source,
        "open": open_target,
        "preview": f"ofti {source} --table | {action}",
        "files": ", ".join(files) if files else "-",
    }


def _add_proc_warning_card(
    cards: list[dict[str, object]],
    title: str,
    payload: dict[str, Any],
    source: str,
) -> None:
    cards.append(
        _card(
            "WARN",
            title,
            payload.get("proc_access_warning"),
            "Live process and running-case discovery may be incomplete.",
            "Review process visibility and tracked/untracked jobs.",
            source,
            [],
        ),
    )


def _sample(items: list[object]) -> str:
    head = "; ".join(str(item) for item in items[:3])
    if len(items) > 3:
        return f"{head}; +{len(items) - 3} more"
    return head


def _path_list(value: object) -> list[str]:
    if not value:
        return []
    return [str(value)]


def _files_from_checks(checks: list[object], *, fallback: list[str]) -> list[str]:
    files = []
    for check in checks:
        key = str(check)
        if "/" in key or "." in key:
            files.append(key)
        elif key == "solver_entry":
            files.append("system/controlDict")
    return files or fallback
