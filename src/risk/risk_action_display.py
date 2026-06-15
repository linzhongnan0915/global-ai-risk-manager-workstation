"""Display-only Risk Action Center status semantics (not financial calculations)."""

from __future__ import annotations

from typing import Any

MIN_LIMIT_METRICS = frozenset({"latest_63d_rolling_sharpe"})


def _is_not_modeled(check: dict[str, Any]) -> bool:
    status = str(check.get("status") or "").lower()
    if status in {"not_modeled", "not_evaluated"}:
        return True
    return check.get("current_value") is None


def _is_min_limit(check: dict[str, Any]) -> bool:
    return str(check.get("metric") or "") in MIN_LIMIT_METRICS


def _is_scenario(check: dict[str, Any]) -> bool:
    scope = str(check.get("scope") or "")
    return scope in {"scenario", "portfolio_scenario"}


def compute_utilization(check: dict[str, Any]) -> float | None:
    if _is_not_modeled(check) or _is_min_limit(check):
        return None
    current = check.get("current_value")
    threshold = check.get("breach_threshold")
    if not isinstance(current, (int, float)) or not isinstance(threshold, (int, float)):
        return check.get("utilization")  # type: ignore[return-value]
    if threshold == 0:
        return None
    if _is_scenario(check):
        return abs(float(current)) / abs(float(threshold))
    return abs(float(current)) / abs(float(threshold))


def status_from_utilization(utilization: float) -> str:
    if utilization > 1.0:
        return "breach"
    if utilization >= 0.90:
        return "warning"
    if utilization >= 0.80:
        return "watch"
    return "ok"


def display_status(check: dict[str, Any]) -> str:
    if _is_not_modeled(check):
        return "not_modeled"
    if _is_min_limit(check):
        status = str(check.get("status") or "ok").lower()
        return "warning" if status == "breach" else status
    utilization = compute_utilization(check)
    if utilization is not None:
        return status_from_utilization(float(utilization))
    return str(check.get("status") or "ok").lower()


def display_gap(check: dict[str, Any]) -> float | None:
    if not _is_min_limit(check) or _is_not_modeled(check):
        return None
    current = check.get("current_value")
    threshold = check.get("breach_threshold")
    if not isinstance(current, (int, float)) or not isinstance(threshold, (int, float)):
        return None
    return float(current) - float(threshold)


def display_action(check: dict[str, Any]) -> str:
    status = display_status(check)
    if status == "not_modeled":
        return "Review model coverage"
    action = str(check.get("required_action") or check.get("action") or "").strip()
    if status == "ok" or action == "Keep" or not action:
        return "—"
    return action


def include_in_current_model(check: dict[str, Any]) -> bool:
    status = display_status(check)
    if status in {"breach", "warning", "not_modeled"}:
        return True
    if status == "watch":
        utilization = compute_utilization(check)
        return utilization is not None and utilization >= 0.80
    return False
