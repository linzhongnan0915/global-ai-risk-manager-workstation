"""Double-checked risk decision review and expected-impact estimates."""

from __future__ import annotations

from typing import Any


RISK_METRICS = {
    "portfolio_volatility": "lower",
    "portfolio_var_99": "lower_abs",
    "portfolio_expected_shortfall_95": "lower_abs",
    "portfolio_max_drawdown": "lower_abs",
    "portfolio_sharpe": "higher",
}


def review_decisions(
    strategy_rows: list[dict[str, Any]],
    allocation: dict[str, Any],
    risk_limits: dict[str, Any],
    factor_analytics: dict[str, Any],
    current_risk: dict[str, float],
    proposed_risk: dict[str, float],
) -> dict[str, Any]:
    """Review candidate decisions before they can be shown as final recommendations."""

    strategy_reviews = [_review_strategy_decision(row) for row in strategy_rows]
    expected_impact = _expected_portfolio_impact(
        current_risk,
        proposed_risk,
        factor_analytics,
        allocation,
        strategy_rows,
    )
    gates = _portfolio_double_checks(strategy_reviews, allocation, risk_limits, expected_impact)
    failed = [gate for gate in gates if gate["status"] == "fail"]
    warnings = [gate for gate in gates if gate["status"] == "warning"]
    if failed:
        final_decision = "Reject / Redesign Proposed Rebalance"
        approval_status = "blocked_pending_modification"
    elif warnings:
        final_decision = "Modify Then Human Review"
        approval_status = "pending_modification_and_human_review"
    else:
        final_decision = "Approve For Human Review"
        approval_status = "pending_human_approval"
    return {
        "candidate_decision": "Review proposed rebalance",
        "final_decision": final_decision,
        "approval_status": approval_status,
        "auto_execution_allowed": False,
        "double_check_summary": {
            "pass": sum(gate["status"] == "pass" for gate in gates),
            "warning": len(warnings),
            "fail": len(failed),
        },
        "double_check_gates": gates,
        "expected_impact": expected_impact,
        "required_modifications": _required_modifications(strategy_reviews, failed, warnings),
        "post_decision_monitoring_plan": _post_decision_monitoring_plan(expected_impact),
        "strategy_decision_reviews": strategy_reviews,
        "decision_limitations": [
            "Expected impact is a historical proxy estimate, not a forecast or guaranteed outcome.",
            "ETF proxy factor exposures are not a licensed Barra model.",
            "Correlation and risk estimates can change after the rebalance.",
            "All real allocation changes require human approval.",
        ],
    }


def _required_modifications(
    strategy_reviews: list[dict[str, Any]],
    failed_gates: list[dict[str, Any]],
    warning_gates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    modifications = []
    for review in strategy_reviews:
        if review["allocation_blocked"]:
            modifications.append(
                {
                    "scope": review["strategy_id"],
                    "required_change": "Remove proposed allocation increase and redesign or justify strategy.",
                    "reason": "Strategy failed at least one blocking evidence, correlation, or risk-direction gate.",
                }
            )
        elif any(check["status"] == "warning" for check in review["checks"]):
            modifications.append(
                {
                    "scope": review["strategy_id"],
                    "required_change": "Hold increase at current weight unless human reviewer documents explicit justification.",
                    "reason": "Strategy is warning-status and should not receive an automatic allocation increase.",
                }
            )
    if warning_gates:
        modifications.append(
            {
                "scope": "portfolio",
                "required_change": "Document why expected risk improvement is worth the estimated return/cost trade-off.",
                "reason": "At least one portfolio double-check gate returned warning.",
            }
        )
    if failed_gates:
        modifications.append(
            {
                "scope": "portfolio",
                "required_change": "Regenerate proposed weights after removing all blocked allocation increases.",
                "reason": "The current proposal cannot proceed while a blocking gate fails.",
            }
        )
    return modifications


def _post_decision_monitoring_plan(expected_impact: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_expectation": {
            "expected_risk_direction": "Core risk metrics should improve or remain stable after approved changes.",
            "expected_cost": expected_impact.get("transaction_cost_dollars", 0.0),
            "expected_net_benefit_proxy_dollars": expected_impact.get("net_expected_annual_benefit_proxy_dollars", 0.0),
            "confidence": expected_impact.get("confidence", "low"),
        },
        "checkpoints": [
            {
                "horizon": "T+1",
                "checks": ["executed transaction cost versus estimate", "position and weight reconciliation", "unexpected factor exposure change"],
            },
            {
                "horizon": "21 trading days",
                "checks": ["realized volatility versus expected direction", "current drawdown", "rolling Sharpe", "limit breaches"],
            },
            {
                "horizon": "63 trading days",
                "checks": ["risk-adjusted performance", "correlation changes", "factor concentration", "decision benefit versus transaction cost"],
            },
        ],
        "invalidation_criteria": [
            "Any new portfolio or strategy breach caused by the allocation change.",
            "Realized transaction cost materially exceeds estimate.",
            "Portfolio volatility, VaR, ES, and drawdown worsen instead of the expected improvement.",
            "A strategy receiving additional capital develops a correlation or evidence blocker.",
            "Expected benefit remains negative after the review horizon.",
        ],
    }


def _review_strategy_decision(row: dict[str, Any]) -> dict[str, Any]:
    trade = row.get("rebalance_trade", {})
    side = trade.get("side", "HOLD")
    evidence_ok = (
        row.get("evidence_status") == "evidence_attached"
        and row.get("allocation_eligibility", {}).get("eligible", True)
    )
    correlation_ok = not row.get("correlation_gate", {}).get("allocation_blocker", False)
    risk_status = row.get("risk_status", "ok")
    direction_ok = not (side == "BUY" and risk_status == "breach")
    warning_increase_ok = not (side == "BUY" and risk_status == "warning")
    candidate = row.get("recommended_action", "Watch")
    checks = [
        _gate("evidence_gate", evidence_ok, "Allocation increase requires complete evidence and research-quality eligibility."),
        _gate("correlation_gate", correlation_ok, "Allocation increase must not add duplicate strategy exposure."),
        _gate("risk_direction_gate", direction_ok, "Do not increase a strategy with breached risk limits."),
        _gate(
            "warning_increase_review",
            warning_increase_ok,
            "Increasing a warning-status strategy requires modification or explicit human justification.",
            failure_status="warning",
        ),
    ]
    blocking = side == "BUY" and any(check["status"] == "fail" for check in checks)
    if blocking:
        final_action = "Reject Increase / Redesign"
    elif side == "SELL" and risk_status == "breach":
        final_action = "Reduce or Pause, Human Review"
    elif side == "BUY" and risk_status == "warning":
        final_action = "Hold Increase, Human Review"
    elif side == "BUY":
        final_action = "Increase Review, Human Approval Required"
    elif side == "SELL":
        final_action = "Reduction Review, Human Approval Required"
    else:
        final_action = candidate
    current_weight = float(row.get("current_weight", 0.0))
    proposed_weight = float(row.get("proposed_weight", 0.0))
    annual_return = float(row.get("net_metrics", {}).get("annual_return", 0.0))
    annual_vol = float(row.get("net_metrics", {}).get("annual_volatility", 0.0))
    return {
        "strategy_id": row.get("strategy_id"),
        "strategy": row.get("name"),
        "candidate_action": candidate,
        "trade_side": side,
        "final_action_after_double_check": final_action,
        "allocation_blocked": blocking,
        "checks": checks,
        "expected_change": {
            "weight_change": proposed_weight - current_weight,
            "annual_return_contribution_change_proxy": (proposed_weight - current_weight) * annual_return,
            "annual_volatility_budget_change_proxy": (proposed_weight - current_weight) * annual_vol,
            "estimated_transaction_cost": float(trade.get("estimated_cost", 0.0)),
        },
    }


def _portfolio_double_checks(
    strategy_reviews: list[dict[str, Any]],
    allocation: dict[str, Any],
    risk_limits: dict[str, Any],
    expected_impact: dict[str, Any],
) -> list[dict[str, Any]]:
    blocked_buys = [row for row in strategy_reviews if row["allocation_blocked"]]
    rebalance_checks = risk_limits.get("rebalance", {}).get("checks", [])
    rebalance_breaches = [check for check in rebalance_checks if check.get("status") == "breach"]
    weight_sum = sum(float(value) for value in allocation.get("proposed_weights", {}).values())
    improved = expected_impact["risk_metric_summary"]["improved"]
    worsened = expected_impact["risk_metric_summary"]["worsened"]
    cost = float(allocation.get("estimated_transaction_cost", 0.0))
    net_expected_benefit = float(expected_impact.get("net_expected_annual_benefit_proxy_dollars", 0.0))
    return [
        _gate(
            "blocked_strategy_buy_check",
            not blocked_buys,
            "Proposed rebalance must not increase breached, duplicate, or evidence-incomplete strategies.",
            details=[row["strategy_id"] for row in blocked_buys],
        ),
        _gate(
            "rebalance_limit_check",
            not rebalance_breaches,
            "Proposed rebalance must remain within turnover and transaction-cost limits.",
            details=[check["limit_id"] for check in rebalance_breaches],
        ),
        _gate(
            "weight_sum_check",
            abs(weight_sum - 1.0) <= 1e-8,
            "Proposed strategy weights must sum to 100%.",
            details={"proposed_weight_sum": weight_sum},
        ),
        _gate(
            "risk_improvement_check",
            improved >= worsened and improved > 0,
            "Proposed allocation should improve at least as many core risk metrics as it worsens.",
            details=expected_impact["risk_metric_summary"],
            failure_status="warning",
        ),
        _gate(
            "cost_benefit_check",
            net_expected_benefit > 0,
            "Expected annual contribution benefit proxy should exceed one-time transaction cost.",
            details={"expected_benefit_proxy_dollars": net_expected_benefit, "transaction_cost_dollars": cost},
            failure_status="warning",
        ),
        {
            "gate": "human_approval_check",
            "status": "pass",
            "explanation": "Real allocation changes remain blocked until a human approves, rejects, or modifies the proposal.",
            "details": {"human_approval_required": True, "auto_execution_allowed": False},
        },
    ]


def _expected_portfolio_impact(
    current_risk: dict[str, float],
    proposed_risk: dict[str, float],
    factor_analytics: dict[str, Any],
    allocation: dict[str, Any],
    strategy_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    metric_changes = []
    improved = 0
    worsened = 0
    unchanged = 0
    for metric, preference in RISK_METRICS.items():
        current = float(current_risk.get(metric, 0.0))
        proposed = float(proposed_risk.get(metric, 0.0))
        delta = proposed - current
        outcome = _metric_outcome(current, proposed, preference)
        improved += outcome == "improved"
        worsened += outcome == "worsened"
        unchanged += outcome == "unchanged"
        metric_changes.append(
            {
                "metric": metric,
                "current": current,
                "proposed": proposed,
                "change": delta,
                "expected_outcome": outcome,
            }
        )
    gross_benefit = sum(
        review_weight_change(row) * float(row.get("net_metrics", {}).get("annual_return", 0.0))
        for row in strategy_rows
    )
    capital = float(allocation.get("capital", 0.0))
    cost = float(allocation.get("estimated_transaction_cost", 0.0))
    gross_benefit_dollars = gross_benefit * capital
    confidence = _expectation_confidence(strategy_rows)
    return {
        "method": "Historical net-return and risk proxy under proposed fixed strategy weights.",
        "confidence": confidence,
        "risk_metric_changes": metric_changes,
        "risk_metric_summary": {"improved": improved, "worsened": worsened, "unchanged": unchanged},
        "factor_exposure_changes": factor_analytics.get("portfolio_factor_change", {}),
        "factor_concentration_change": {
            "current": factor_analytics.get("portfolio_factor_concentration_current", {}),
            "proposed": factor_analytics.get("portfolio_factor_concentration_proposed", {}),
        },
        "gross_expected_annual_benefit_proxy_return": gross_benefit,
        "gross_expected_annual_benefit_proxy_dollars": gross_benefit_dollars,
        "transaction_cost_dollars": cost,
        "net_expected_annual_benefit_proxy_dollars": gross_benefit_dollars - cost,
        "expectation_horizon": "annualized historical proxy with one-time rebalance cost",
        "not_a_forecast": True,
    }


def review_weight_change(row: dict[str, Any]) -> float:
    return float(row.get("proposed_weight", 0.0)) - float(row.get("current_weight", 0.0))


def _metric_outcome(current: float, proposed: float, preference: str) -> str:
    tolerance = 1e-10
    if abs(proposed - current) <= tolerance:
        return "unchanged"
    if preference == "higher":
        return "improved" if proposed > current else "worsened"
    if preference == "lower_abs":
        return "improved" if abs(proposed) < abs(current) else "worsened"
    return "improved" if proposed < current else "worsened"


def _expectation_confidence(strategy_rows: list[dict[str, Any]]) -> str:
    if not strategy_rows:
        return "low"
    complete = sum(row.get("evidence_status") == "evidence_attached" for row in strategy_rows)
    positive_oos = sum(float(row.get("walk_forward", {}).get("positive_window_rate", 0.0)) >= 0.50 for row in strategy_rows)
    ratio = min(complete, positive_oos) / len(strategy_rows)
    if ratio >= 0.80:
        return "medium"
    return "low"


def _gate(
    name: str,
    passed: bool,
    explanation: str,
    details: Any = None,
    failure_status: str = "fail",
) -> dict[str, Any]:
    return {
        "gate": name,
        "status": "pass" if passed else failure_status,
        "explanation": explanation,
        "details": details,
    }
