"""Risk recommendation layer combining market, news, and portfolio signals."""

from __future__ import annotations

from typing import Any


def build_recommendations(
    market_summary: list[dict[str, Any]],
    news_risk: dict[str, Any],
    allocation_summary: dict[str, Any],
    factor_checks: list[dict[str, Any]] | None = None,
    portfolio_limit_checks: list[dict[str, Any]] | None = None,
    factor_exposure: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    factor_checks = factor_checks or []
    portfolio_limit_checks = portfolio_limit_checks or []
    factor_exposure = factor_exposure or {}

    for check in factor_checks:
        if check.get("status") == "breach":
            recommendations.append(
                {
                    "priority": "high",
                    "action": f"Reduce {check.get('metric', 'factor')} exposure",
                    "rationale": check.get("action") or check.get("explanation") or "Factor limit breach requires remediation before approval.",
                    "approval_required": True,
                    "category": "factor_risk",
                }
            )
        elif check.get("status") in {"watch", "warning"}:
            recommendations.append(
                {
                    "priority": "medium",
                    "action": f"Review {check.get('metric', 'factor')} utilization",
                    "rationale": check.get("action") or check.get("explanation") or "Factor utilization elevated.",
                    "approval_required": True,
                    "category": "factor_risk",
                }
            )

    for check in portfolio_limit_checks:
        if check.get("status") == "breach" and check.get("metric") not in {row.get("metric") for row in factor_checks}:
            recommendations.append(
                {
                    "priority": "high",
                    "action": f"Address portfolio limit: {check.get('metric')}",
                    "rationale": check.get("explanation") or "Portfolio hard limit breached.",
                    "approval_required": True,
                    "category": "portfolio_limit",
                }
            )

    if factor_exposure:
        top_factor = max(factor_exposure, key=lambda key: abs(float(factor_exposure[key])))
        top_value = float(factor_exposure[top_factor])
        if abs(top_value) >= 0.35:
            recommendations.append(
                {
                    "priority": "medium",
                    "action": "Review factor concentration",
                    "rationale": f"Largest absolute portfolio factor exposure is {top_factor.replace('_', ' ')} at {top_value:.2f}.",
                    "approval_required": True,
                    "category": "factor_concentration",
                }
            )

    if news_risk["watch_level"] in {"watch", "urgent_review"}:
        recommendations.append(
            {
                "priority": "high" if news_risk["watch_level"] == "urgent_review" else "medium",
                "action": "Review news-linked factor risks",
                "rationale": "News risk score is elevated. Cross-check affected factors before approving allocation changes.",
                "approval_required": True,
                "category": "news",
            }
        )
    stressed_markets = [row for row in market_summary if row["status"] == "warning"]
    if stressed_markets:
        recommendations.append(
            {
                "priority": "medium",
                "action": "Review drawdown and hedge budget",
                "rationale": "One or more market proxies moved into warning status.",
                "affected_tickers": [row["ticker"] for row in stressed_markets],
                "approval_required": True,
                "category": "market",
            }
        )
    if allocation_summary.get("approval_required"):
        recommendations.append(
            {
                "priority": "medium",
                "action": "Review proposed rebalance",
                "rationale": allocation_summary.get("rationale", "Allocation proposal requires risk manager approval."),
                "estimated_transaction_cost": allocation_summary.get("estimated_transaction_cost"),
                "approval_required": True,
                "category": "allocation",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "priority": "low",
                "action": "Keep current allocation",
                "rationale": "No elevated market, news, or factor warning in current snapshot.",
                "approval_required": False,
                "category": "monitor",
            }
        )
    return recommendations

