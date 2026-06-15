"""Canonical rebalance simulation for before/after risk and limit checks."""

from __future__ import annotations

from typing import Any, Mapping

from src.allocation.rebalance_gates import evaluate_proposal_gates
from src.risk.engine import portfolio_risk_summary, weighted_portfolio_returns
from src.risk.limits import (
    evaluate_factor_limits,
    evaluate_portfolio_limits,
    evaluate_rebalance_limits,
    load_risk_limits,
    worst_status,
)
from src.risk.performance import max_drawdown
from src.risk.transaction_cost import TransactionCostModel


def _weight_turnover(current_weights: Mapping[str, float], target_weights: Mapping[str, float]) -> float:
    strategy_ids = set(current_weights) | set(target_weights)
    return float(sum(abs(target_weights.get(key, 0.0) - current_weights.get(key, 0.0)) for key in strategy_ids))


def _aggregate_factor_exposure(
    strategy_rows: list[dict[str, Any]],
    weights: Mapping[str, float],
) -> dict[str, float]:
    exposure: dict[str, float] = {}
    for row in strategy_rows:
        weight = float(weights.get(row["strategy_id"], 0.0))
        if weight <= 0:
            continue
        latest = row.get("factor_exposure", {}).get("latest", {})
        for factor, value in latest.items():
            exposure[factor] = exposure.get(factor, 0.0) + weight * float(value)
    return exposure


def _factor_concentration(exposure: Mapping[str, float]) -> dict[str, float]:
    values = [abs(float(value)) for value in exposure.values()]
    total = sum(values)
    if total <= 0:
        return {"herfindahl_abs_exposure": 0.0, "top_factor_share": 0.0}
    shares = [value / total for value in values]
    herfindahl = sum(share * share for share in shares)
    top_share = max(shares) if shares else 0.0
    return {"herfindahl_abs_exposure": float(herfindahl), "top_factor_share": float(top_share)}


def _factor_analytics_for_weights(
    strategy_rows: list[dict[str, Any]],
    current_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
) -> dict[str, Any]:
    current_exposure = _aggregate_factor_exposure(strategy_rows, current_weights)
    proposed_exposure = _aggregate_factor_exposure(strategy_rows, target_weights)
    factor_change = {
        factor: float(proposed_exposure.get(factor, 0.0) - current_exposure.get(factor, 0.0))
        for factor in sorted(set(current_exposure) | set(proposed_exposure))
    }
    return {
        "portfolio_factor_exposure_current": current_exposure,
        "portfolio_factor_exposure_proposed": proposed_exposure,
        "portfolio_factor_change": factor_change,
        "portfolio_factor_concentration_current": _factor_concentration(current_exposure),
        "portfolio_factor_concentration_proposed": _factor_concentration(proposed_exposure),
    }


def _factor_analytics_for_limit_evaluation(factor_analytics: dict[str, Any]) -> dict[str, Any]:
    """Evaluate proposed factor limits using post-rebalance exposure."""

    proposed = factor_analytics.get("portfolio_factor_exposure_proposed", {})
    return {
        **factor_analytics,
        "portfolio_factor_exposure_current": proposed,
        "portfolio_factor_concentration_current": factor_analytics.get(
            "portfolio_factor_concentration_proposed",
            _factor_concentration(proposed),
        ),
    }


def _governance_checks(
    strategy_rows: list[dict[str, Any]],
    current_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
    risk_limit_config: dict[str, Any],
    max_single_strategy_weight: float,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    total = float(sum(target_weights.values()))
    cash = max(0.0, 1.0 - total)
    cash_threshold = float(risk_limit_config.get("factor_limits", {}).get("cash_review_threshold", 0.60))
    if total > 1.000001:
        invested_status = "breach"
        invested_text = f"{total:.1%} invested; cash is {cash:.1%}. Invested weight cannot exceed 100%."
    elif cash >= cash_threshold:
        invested_status = "watch"
        invested_text = f"{total:.1%} invested; cash is {cash:.1%}. High cash sleeve requires review."
    else:
        invested_status = "ok"
        invested_text = f"{total:.1%} invested; cash is {cash:.1%}. Under-investment is allowed; residual cash is explicit."
    checks.append({"status": invested_status, "metric": "Invested weight", "text": invested_text})
    checks.append(
        {
            "status": "ok",
            "metric": "Cash sleeve",
            "text": f"Residual cash {cash:.1%} is not a strategy allocation and is not crash-blocking.",
        }
    )
    turnover = _weight_turnover(current_weights, target_weights)
    max_turnover = float(risk_limit_config["portfolio_limits"].get("max_turnover_per_rebalance", 0.15))
    checks.append(
        {
            "status": "ok" if turnover <= max_turnover else "warning",
            "metric": "Turnover",
            "text": f"{turnover:.1%} proposed versus {max_turnover:.1%} review threshold.",
        }
    )
    for row in strategy_rows:
        strategy_id = row["strategy_id"]
        target = float(target_weights.get(strategy_id, 0.0))
        current = float(current_weights.get(strategy_id, 0.0))
        if target > max_single_strategy_weight:
            checks.append(
                {
                    "status": "breach",
                    "metric": row.get("name", strategy_id),
                    "text": f"{target:.1%} exceeds the {max_single_strategy_weight:.1%} strategy cap.",
                }
            )
        eligible = bool(row.get("allocation_eligibility", {}).get("eligible", False))
        if not eligible and target > 0:
            checks.append(
                {
                    "status": "breach",
                    "metric": row.get("name", strategy_id),
                    "text": "Research-only strategy cannot receive live allocation.",
                }
            )
        if target > current and row.get("risk_status") not in {"ok", "watch"}:
            checks.append(
                {
                    "status": "warning",
                    "metric": row.get("name", strategy_id),
                    "text": f"Increasing a {row.get('risk_status', 'unknown')} strategy requires explicit human justification.",
                }
            )
    return checks


def simulate_rebalance(
    strategy_returns: Mapping[str, list[float]],
    strategy_rows: list[dict[str, Any]],
    current_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
    capital: float,
    risk_limit_config: dict[str, Any] | None = None,
    cost_model: TransactionCostModel | None = None,
) -> dict[str, Any]:
    """Compute before/after portfolio risk, costs, and governance checks.

    Inputs
    ------
    strategy_returns:
        Aligned net daily return series keyed by strategy_id.
    strategy_rows:
        Strategy metadata rows from the dashboard artifact.
    current_weights / target_weights:
        Portfolio weights before and after the proposed rebalance.
    capital:
        Portfolio capital used for transaction-cost dollars.

    Outputs
    -------
    Dictionary with current/proposed risk metrics, turnover, estimated cost,
    factor exposure before/after, and limit/governance checks.
    """

    limits = risk_limit_config or load_risk_limits()
    model = cost_model or TransactionCostModel()
    current = {key: float(value) for key, value in current_weights.items()}
    target = {key: float(value) for key, value in target_weights.items()}
    invested_total = sum(target.values())

    risk_before = portfolio_risk_summary(strategy_returns, current, allow_residual_cash=True)
    if invested_total <= 1.000001:
        risk_after = portfolio_risk_summary(strategy_returns, target, allow_residual_cash=True)
    else:
        risk_after = {
            "portfolio_sharpe": 0.0,
            "portfolio_volatility": 0.0,
            "portfolio_var_99": 0.0,
            "portfolio_expected_shortfall_95": 0.0,
            "portfolio_max_drawdown": 0.0,
        }
    turnover = _weight_turnover(current, target)
    estimated_cost = model.rebalance_cost(current, target, capital)
    factor_analytics = _factor_analytics_for_weights(strategy_rows, current, target)
    factor_limit_status = evaluate_factor_limits(_factor_analytics_for_limit_evaluation(factor_analytics), limits)
    factor_before_status = evaluate_factor_limits(
        {
            **factor_analytics,
            "portfolio_factor_exposure_current": factor_analytics["portfolio_factor_exposure_current"],
            "portfolio_factor_concentration_current": factor_analytics["portfolio_factor_concentration_current"],
        },
        limits,
    )
    portfolio_before_status = evaluate_portfolio_limits(risk_before, limits)
    portfolio_after_status = evaluate_portfolio_limits(risk_after, limits) if invested_total <= 1.000001 else {"checks": []}
    rebalance_limit_status = evaluate_rebalance_limits(
        {
            "weight_changes": {key: target.get(key, 0.0) - current.get(key, 0.0) for key in set(current) | set(target)},
            "turnover": turnover,
            "estimated_transaction_cost": estimated_cost,
            "capital": capital,
        },
        limits,
    )
    governance_checks = _governance_checks(
        strategy_rows,
        current,
        target,
        limits,
        float(limits["strategy_limits"].get("max_weight_default", 0.15)),
    )
    for check in factor_limit_status["checks"]:
        if check.get("status") == "not_modeled" or check.get("current_value") is None:
            governance_checks.append(
                {
                    "status": check["status"],
                    "metric": check["metric"],
                    "text": check.get("explanation", "Proxy loading not modeled in the current weighted simulation."),
                }
            )
            continue
        governance_checks.append(
            {
                "status": check["status"],
                "metric": check["metric"],
                "text": (
                    f"Simulated exposure {check['current_value']:.3f} versus "
                    f"hard limit {check['breach_threshold']:.3f}. {check.get('explanation', '')}"
                ).strip(),
            }
        )
    for check in rebalance_limit_status["checks"]:
        if check["status"] != "ok":
            governance_checks.append(
                {
                    "status": check["status"],
                    "metric": check["metric"],
                    "text": check.get("explanation", check.get("action", "Rebalance limit check failed.")),
                }
            )

    proposal_gates = evaluate_proposal_gates(
        portfolio_before_status["checks"] + factor_before_status["checks"],
        portfolio_after_status["checks"] + factor_limit_status["checks"],
        turnover=turnover,
    )
    for gate in proposal_gates:
        if gate.get("status") != "ok":
            governance_checks.append(
                {
                    "status": gate["status"],
                    "metric": gate.get("metric", "proposal_gate"),
                    "text": gate.get("text", ""),
                    "gate": gate.get("gate"),
                    "required_action": gate.get("required_action"),
                }
            )

    current_drawdown = max_drawdown(
        weighted_portfolio_returns(strategy_returns, current, allow_residual_cash=True)
    )
    proposed_drawdown = (
        max_drawdown(weighted_portfolio_returns(strategy_returns, target, allow_residual_cash=True))
        if invested_total <= 1.000001
        else 0.0
    )

    return {
        "source": "python_rebalance_simulation",
        "current_weights": current,
        "target_weights": target,
        "turnover": turnover,
        "estimated_transaction_cost": estimated_cost,
        "metrics_before": {
            **risk_before,
            "portfolio_current_drawdown": current_drawdown,
        },
        "metrics_after": {
            **risk_after,
            "portfolio_current_drawdown": proposed_drawdown,
        },
        "factor_exposure_before": factor_analytics["portfolio_factor_exposure_current"],
        "factor_exposure_after": factor_analytics["portfolio_factor_exposure_proposed"],
        "factor_concentration_before": factor_analytics["portfolio_factor_concentration_current"],
        "factor_concentration_after": factor_analytics["portfolio_factor_concentration_proposed"],
        "factor_change": factor_analytics["portfolio_factor_change"],
        "cash_weight": max(0.0, 1.0 - invested_total),
        "proposal_gates": proposal_gates,
        "checks": governance_checks,
        "summary_status": worst_status(governance_checks),
        "optimizer_label": "heuristic_score_based_proposal_not_fully_constrained",
        "limitations": [
            "Simulation uses aligned historical net strategy returns; realized post-rebalance outcomes can differ.",
            "Correlation structure is held fixed; duplicate-exposure classification does not change with weights alone.",
            "Approval records a human decision only; execution remains disabled in this prototype.",
        ],
    }


def build_simulation_context(
    strategy_returns: Mapping[str, list[float]],
    strategy_rows: list[dict[str, Any]],
    current_weights: Mapping[str, float],
    proposed_weights: Mapping[str, float],
    capital: float,
    risk_limit_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build artifact-embedded simulation context and official optimizer scenarios."""

    limits = risk_limit_config or load_risk_limits()
    official = simulate_rebalance(
        strategy_returns,
        strategy_rows,
        current_weights,
        proposed_weights,
        capital,
        limits,
    )
    baseline = simulate_rebalance(
        strategy_returns,
        strategy_rows,
        current_weights,
        current_weights,
        capital,
        limits,
    )
    observations = len(next(iter(strategy_returns.values()))) if strategy_returns else 0
    return {
        "strategy_return_keys": sorted(strategy_returns.keys()),
        "return_observations": observations,
        "annualization_days": 252,
        "transaction_cost_bps": {"buy": 5.0, "sell": 5.0},
        "cash_policy": "residual_cash_explicit_no_crash_on_underinvestment",
        "official_optimizer": official,
        "current_baseline": baseline,
    }
