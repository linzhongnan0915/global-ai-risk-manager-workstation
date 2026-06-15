"""Canonical scoped risk-status aggregation for dashboard artifacts."""

from __future__ import annotations

from typing import Any

from src.risk.limits import summarize_limit_status, worst_status
from src.risk.metric_availability import metric_value

HEADLINE_SCOPES = (
    "portfolio_live",
    "allocated_strategy_live",
    "factor",
    "scenario",
    "correlation",
    "rebalance",
    "data_quality",
)

RESEARCH_SCOPES = ("research_quality",)


def _research_quality_label(status: str) -> str:
    if status == "breach":
        return "fail"
    if status in {"watch", "warning"}:
        return "watch"
    return "pass"


def _allocation_eligibility_label(strategy: dict[str, Any]) -> str:
    eligibility = strategy.get("allocation_eligibility", {})
    if eligibility.get("eligible"):
        return "eligible"
    if strategy.get("correlation_gate", {}).get("allocation_blocker"):
        return "blocked"
    if strategy.get("research_quality_status") == "fail":
        return "blocked"
    return "pending"


def enrich_check(
    check: dict[str, Any],
    *,
    scope: str,
    subject_id: str,
    allocation_relevance: str,
    applicability: str,
) -> dict[str, Any]:
    return {
        **check,
        "check_id": check.get("limit_id") or check.get("metric"),
        "scope": scope,
        "subject_id": subject_id,
        "severity": check.get("status", "ok"),
        "required_action": check.get("action", "Keep"),
        "allocation_relevance": allocation_relevance,
        "applicability": applicability,
    }


def _scope_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [check for check in checks if check.get("status") not in {"not_evaluated", "not_modeled"}]
    summary = summarize_limit_status(evaluated)
    return {
        "summary": summary,
        "checks": checks,
        "worst_status": worst_status(evaluated),
    }


def build_risk_status_summary(
    *,
    portfolio_checks: list[dict[str, Any]],
    allocated_strategy_checks: list[dict[str, Any]],
    research_quality_checks: list[dict[str, Any]],
    factor_checks: list[dict[str, Any]],
    scenario_checks: list[dict[str, Any]],
    correlation_checks: list[dict[str, Any]],
    rebalance_checks: list[dict[str, Any]],
    residual_cash_checks: list[dict[str, Any]],
    data_quality_checks: list[dict[str, Any]] | None = None,
    governance_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    portfolio_scope = _scope_summary(portfolio_checks)
    allocated_scope = _scope_summary(allocated_strategy_checks)
    factor_scope = _scope_summary(factor_checks)
    scenario_scope = _scope_summary(scenario_checks)
    correlation_scope = _scope_summary(correlation_checks)
    rebalance_scope = _scope_summary(rebalance_checks)
    research_scope = _scope_summary(research_quality_checks)
    data_scope = _scope_summary(data_quality_checks or [])
    governance_scope = _scope_summary(governance_checks or [])
    residual_scope = _scope_summary(residual_cash_checks)

    scopes = {
        "portfolio_live": portfolio_scope,
        "allocated_strategy_live": allocated_scope,
        "research_quality": research_scope,
        "factor": factor_scope,
        "scenario": scenario_scope,
        "correlation": correlation_scope,
        "rebalance": rebalance_scope,
        "residual_cash": residual_scope,
        "data_quality": data_scope,
        "governance": governance_scope,
    }

    blocking_breaches = 0
    warnings = 0
    seen_ids: set[str] = set()
    for scope_name in HEADLINE_SCOPES:
        for check in scopes[scope_name]["checks"]:
            check_id = str(check.get("check_id") or check.get("limit_id") or check.get("metric"))
            if check_id in seen_ids:
                continue
            seen_ids.add(check_id)
            if check.get("status") == "breach":
                blocking_breaches += 1
            elif check.get("status") in {"watch", "warning"}:
                warnings += 1

    if blocking_breaches:
        headline_status = "action_required"
    elif warnings:
        headline_status = "watch"
    else:
        headline_status = "within_limits"

    return {
        "headline": {
            "status": headline_status,
            "blocking_breaches": blocking_breaches,
            "warnings": warnings,
            "included_scopes": list(HEADLINE_SCOPES),
            "excluded_from_headline": list(RESEARCH_SCOPES),
        },
        "scopes": scopes,
        "policy_note": (
            "Headline counts include portfolio, allocated-model, factor, scenario, "
            "correlation, rebalance, and data-quality scopes. Research-quality failures "
            "are tracked separately and may block allocation eligibility without entering "
            "allocated-live breach totals."
        ),
    }


def decorate_strategy_status_fields(strategy: dict[str, Any]) -> dict[str, Any]:
    """Attach canonical live/research status fields to a strategy row."""

    current_weight = float(strategy.get("current_weight", 0.0))
    research_status = strategy.get("research_status", "ok")
    strategy["research_quality_status"] = _research_quality_label(research_status)
    if current_weight <= 0:
        strategy["live_risk_status"] = "not_applicable"
    else:
        strategy["live_risk_status"] = strategy.get("risk_status", "ok")
    eligibility = strategy.get("allocation_eligibility", {})
    strategy["allocation_eligibility"] = {
        **eligibility,
        "label": _allocation_eligibility_label(strategy),
    }
    return strategy
