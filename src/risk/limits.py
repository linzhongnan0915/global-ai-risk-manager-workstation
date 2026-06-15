"""Risk limit evaluation for portfolio and strategy workstation artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_risk_limits(path: str | Path = "data/config/risk_limits.yaml") -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def evaluate_max_limit(
    limit_id: str,
    scope: str,
    metric: str,
    current_value: float,
    breach_threshold: float,
    action: str,
    explanation: str,
) -> dict[str, Any]:
    """Evaluate a maximum-style limit where larger absolute risk is worse."""

    current_abs = abs(float(current_value))
    breach_abs = abs(float(breach_threshold))
    if breach_abs:
        utilization = current_abs / breach_abs
        status = "warning" if current_abs <= breach_abs + 1e-12 and utilization >= 0.80 else _status_from_utilization(utilization)
    else:
        utilization = 0.0 if current_abs == 0 else 1.0
        status = "ok" if current_abs == 0 else "breach"
    return {
        "limit_id": limit_id,
        "scope": scope,
        "metric": metric,
        "current_value": float(current_value),
        "watch_threshold": 0.60 * breach_abs,
        "warning_threshold": 0.80 * breach_abs,
        "breach_threshold": float(breach_threshold),
        "utilization": float(utilization),
        "status": status,
        "action": action if status in {"warning", "breach"} else "Keep",
        "explanation": explanation,
    }


def evaluate_min_limit(
    limit_id: str,
    scope: str,
    metric: str,
    current_value: float,
    breach_threshold: float,
    action: str,
    explanation: str,
) -> dict[str, Any]:
    """Evaluate a minimum-style limit where lower values are worse."""

    current = float(current_value)
    threshold = float(breach_threshold)
    if current >= threshold:
        utilization = 0.0
        status = "ok"
    else:
        shortfall = threshold - current
        utilization = shortfall / abs(threshold) if threshold else 1.0
        status = _status_from_utilization(utilization)
    return {
        "limit_id": limit_id,
        "scope": scope,
        "metric": metric,
        "current_value": current,
        "watch_threshold": threshold * 1.40,
        "warning_threshold": threshold * 1.15,
        "breach_threshold": threshold,
        "utilization": float(utilization),
        "status": status,
        "action": action if status in {"warning", "breach"} else "Keep",
        "explanation": explanation,
    }


def evaluate_monitor_min_limit(
    limit_id: str,
    scope: str,
    metric: str,
    current_value: float,
    warning_threshold: float,
    action: str,
    explanation: str,
) -> dict[str, Any]:
    """Evaluate a performance-deterioration monitor that cannot create a hard breach alone."""

    check = evaluate_min_limit(limit_id, scope, metric, current_value, warning_threshold, action, explanation)
    if check["status"] == "breach":
        check["status"] = "warning"
    check["hard_limit"] = False
    check["explanation"] = f"{explanation} This is a performance warning, not a standalone hard risk breach."
    return check


def evaluate_portfolio_limits(risk_summary: dict[str, float], config: dict[str, Any] | None = None) -> dict[str, Any]:
    limits = config or load_risk_limits()
    portfolio_limits = limits["portfolio_limits"]
    checks = [
        evaluate_max_limit(
            "PORT_VOL",
            "portfolio",
            "annualized_volatility",
            risk_summary.get("portfolio_volatility", 0.0),
            portfolio_limits["max_annualized_volatility"],
            "Reduce risk or rebalance",
            "Portfolio annualized volatility versus configured risk budget.",
        ),
        evaluate_max_limit(
            "PORT_MAX_DD",
            "portfolio",
            "max_drawdown",
            risk_summary.get("portfolio_max_drawdown", 0.0),
            portfolio_limits["max_drawdown"],
            "Pause risk adds and review drawdown",
            "Portfolio max drawdown versus configured drawdown limit.",
        ),
        evaluate_max_limit(
            "PORT_VAR_99",
            "portfolio",
            "var_99_1d",
            risk_summary.get("portfolio_var_99", 0.0),
            portfolio_limits["max_var_99_1d"],
            "Reduce or hedge tail exposure",
            "Portfolio 1-day 99% VaR versus configured VaR budget.",
        ),
        evaluate_max_limit(
            "PORT_ES_95",
            "portfolio",
            "expected_shortfall_95_1d",
            risk_summary.get("portfolio_expected_shortfall_95", 0.0),
            portfolio_limits["max_expected_shortfall_95_1d"],
            "Reduce or hedge tail exposure",
            "Portfolio 1-day 95% Expected Shortfall versus configured ES budget.",
        ),
    ]
    return {"checks": checks, "summary": summarize_limit_status(checks)}


def evaluate_strategy_limits(strategy: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate live/current monitoring limits for allocated model strategies only."""

    if float(strategy.get("current_weight", 0.0)) <= 0:
        return {
            "checks": [],
            "summary": {"ok": 0, "watch": 0, "warning": 0, "breach": 0},
            "category": "live_monitoring",
            "applicability": "not_applicable",
            "reason": "Zero model allocation; allocated-model monitoring limits do not apply.",
        }

    limits = config or load_risk_limits()
    strategy_limits = limits["strategy_limits"]
    risk_packet = strategy.get("risk_packet", {})
    current_drawdown = risk_packet.get("drawdown_behavior", {}).get("current_drawdown", 0.0)
    stability = risk_packet.get("time_stability", {})
    latest = stability.get("63d", {})
    checks = [
        evaluate_max_limit(
            f"{strategy['strategy_id']}_CURRENT_DD",
            strategy["strategy_id"],
            "current_drawdown",
            current_drawdown,
            strategy_limits["max_current_drawdown"],
            "Reduce or pause pending human review",
            "Current strategy drawdown versus the live monitoring drawdown limit.",
        ),
        evaluate_max_limit(
            f"{strategy['strategy_id']}_ROLLING_VOL",
            strategy["strategy_id"],
            "latest_63d_rolling_volatility",
            latest.get("latest_rolling_volatility", 0.0),
            strategy_limits["max_rolling_volatility"],
            "Reduce or hedge",
            "Latest 63-day rolling volatility versus the live monitoring limit.",
        ),
        evaluate_monitor_min_limit(
            f"{strategy['strategy_id']}_ROLLING_SHARPE",
            strategy["strategy_id"],
            "latest_63d_rolling_sharpe",
            latest.get("latest_rolling_sharpe", 0.0),
            strategy_limits["min_current_rolling_sharpe"],
            "Watch for live strategy deterioration",
            "Latest 63-day rolling Sharpe versus the live deterioration threshold.",
        ),
    ]
    return {"checks": checks, "summary": summarize_limit_status(checks), "category": "live_monitoring", "applicability": "allocated_model"}


def evaluate_residual_cash_limit(
    invested_weight: float,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate unallocated residual cash versus configured maximum."""

    limits = config or load_risk_limits()
    threshold = float(limits["portfolio_limits"].get("max_unallocated_residual_cash_weight", 0.05))
    residual = float(max(0.0, 1.0 - invested_weight))
    check = evaluate_max_limit(
        "PORT_RESIDUAL_CASH",
        "portfolio_residual_cash",
        "unallocated_residual_cash_weight",
        residual,
        threshold,
        "Invest residual cash or document intentional cash sleeve",
        "Unallocated residual cash is separate from Treasury-bill proxy exposure inside strategies.",
    )
    check["display_label"] = "Unallocated residual cash"
    return {"checks": [check], "summary": summarize_limit_status([check])}


def evaluate_portfolio_limits_with_availability(
    operating_metrics: dict[str, dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate portfolio limits only for operating-period metrics marked available."""

    limits = config or load_risk_limits()
    portfolio_limits = limits["portfolio_limits"]
    checks: list[dict[str, Any]] = []

    def _not_evaluated(metric_key: str, wrapped: dict[str, Any] | None, limit_id: str) -> dict[str, Any]:
        return {
            "limit_id": limit_id,
            "scope": "portfolio_live",
            "metric": metric_key,
            "current_value": None,
            "watch_threshold": None,
            "warning_threshold": None,
            "breach_threshold": None,
            "utilization": 0.0,
            "status": "not_evaluated",
            "action": "Keep",
            "explanation": (wrapped or {}).get("reason", "Metric unavailable for operating-period limit evaluation."),
            "applicability": "operating_period",
        }

    vol_wrapped = operating_metrics.get("portfolio_volatility")
    if vol_wrapped and vol_wrapped.get("available"):
        checks.append(
            evaluate_max_limit(
                "PORT_VOL",
                "portfolio_live",
                "annualized_volatility",
                float(vol_wrapped["value"]),
                portfolio_limits["max_annualized_volatility"],
                "Reduce risk or rebalance",
                "Operating-period portfolio annualized volatility versus configured risk budget.",
            )
        )
    else:
        checks.append(_not_evaluated("annualized_volatility", vol_wrapped, "PORT_VOL"))

    dd_wrapped = operating_metrics.get("portfolio_max_drawdown")
    if dd_wrapped and dd_wrapped.get("available"):
        checks.append(
            evaluate_max_limit(
                "PORT_MAX_DD",
                "portfolio_live",
                "max_drawdown",
                float(dd_wrapped["value"]),
                portfolio_limits["max_drawdown"],
                "Pause risk adds and review drawdown",
                "Operating-period portfolio max drawdown versus configured drawdown limit.",
            )
        )
    else:
        checks.append(_not_evaluated("max_drawdown", dd_wrapped, "PORT_MAX_DD"))

    var_wrapped = operating_metrics.get("portfolio_var_99")
    if var_wrapped and var_wrapped.get("available"):
        checks.append(
            evaluate_max_limit(
                "PORT_VAR_99",
                "portfolio_live",
                "var_99_1d",
                float(var_wrapped["value"]),
                portfolio_limits["max_var_99_1d"],
                "Reduce or hedge tail exposure",
                "Operating-period portfolio 1-day 99% VaR versus configured VaR budget.",
            )
        )
    else:
        checks.append(_not_evaluated("var_99_1d", var_wrapped, "PORT_VAR_99"))

    es_wrapped = operating_metrics.get("portfolio_expected_shortfall_95")
    if es_wrapped and es_wrapped.get("available"):
        checks.append(
            evaluate_max_limit(
                "PORT_ES_95",
                "portfolio_live",
                "expected_shortfall_95_1d",
                float(es_wrapped["value"]),
                portfolio_limits["max_expected_shortfall_95_1d"],
                "Reduce or hedge tail exposure",
                "Operating-period portfolio 1-day 95% Expected Shortfall versus configured ES budget.",
            )
        )
    else:
        checks.append(_not_evaluated("expected_shortfall_95_1d", es_wrapped, "PORT_ES_95"))

    evaluated = [check for check in checks if check.get("status") != "not_evaluated"]
    return {"checks": checks, "summary": summarize_limit_status(evaluated)}


def evaluate_research_quality_limits(strategy: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate whether historical evidence is strong enough for allocation eligibility."""

    limits = config or load_risk_limits()
    quality_limits = limits["research_quality_limits"]
    metrics = strategy.get("proxy_metrics", {})
    checks = [
        evaluate_max_limit(
            f"{strategy['strategy_id']}_HISTORICAL_MAX_DD",
            strategy["strategy_id"],
            "historical_max_drawdown",
            metrics.get("proxy_max_drawdown", 0.0),
            quality_limits["max_historical_drawdown"],
            "Research hold or redesign",
            "Full-history maximum drawdown is a research-quality gate, not a live breach.",
        ),
        evaluate_min_limit(
            f"{strategy['strategy_id']}_FULL_HISTORY_SHARPE",
            strategy["strategy_id"],
            "full_history_sharpe",
            metrics.get("proxy_sharpe", 0.0),
            quality_limits["min_full_history_sharpe"],
            "Research hold or redesign",
            "Full-history net Sharpe must be positive for allocation eligibility.",
        ),
        evaluate_max_limit(
            f"{strategy['strategy_id']}_TURNOVER",
            strategy["strategy_id"],
            "annualized_turnover",
            strategy.get("turnover", {}).get("annualized_turnover", 0.0),
            quality_limits["max_annualized_turnover"],
            "Reduce rebalance frequency or redesign signal",
            "Annualized strategy turnover versus the research implementation budget.",
        ),
        evaluate_max_limit(
            f"{strategy['strategy_id']}_COST_DRAG",
            strategy["strategy_id"],
            "annualized_transaction_cost_drag",
            strategy.get("turnover", {}).get("annualized_cost_drag", 0.0),
            quality_limits["max_transaction_cost_drag_annualized"],
            "Reduce turnover or pause strategy",
            "Annualized transaction cost drag versus the research implementation budget.",
        ),
        evaluate_min_limit(
            f"{strategy['strategy_id']}_OOS_WINDOWS",
            strategy["strategy_id"],
            "walk_forward_window_count",
            strategy.get("walk_forward", {}).get("number_of_windows", 0),
            quality_limits["min_walk_forward_windows"],
            "Research Hold",
            "Walk-forward test window count versus minimum evidence requirement.",
        ),
        evaluate_min_limit(
            f"{strategy['strategy_id']}_OOS_POSITIVE_RATE",
            strategy["strategy_id"],
            "positive_oos_window_rate",
            strategy.get("walk_forward", {}).get("positive_window_rate", 0.0),
            quality_limits["min_positive_oos_window_rate"],
            "Watch or Research Hold",
            "Positive out-of-sample window rate versus minimum stability threshold.",
        ),
        evaluate_min_limit(
            f"{strategy['strategy_id']}_OOS_SHARPE",
            strategy["strategy_id"],
            "average_oos_sharpe",
            strategy.get("walk_forward", {}).get("average_test_sharpe", 0.0),
            quality_limits["min_average_oos_sharpe"],
            "Watch or Research Hold",
            "Average out-of-sample Sharpe versus minimum evidence threshold.",
        ),
    ]
    return {"checks": checks, "summary": summarize_limit_status(checks), "category": "research_quality"}


def _factor_not_modeled(
    limit_id: str,
    factor: str,
    breach_threshold: float,
    explanation: str,
) -> dict[str, Any]:
    return {
        "limit_id": limit_id,
        "scope": "portfolio_factor",
        "metric": factor,
        "current_value": None,
        "watch_threshold": None,
        "warning_threshold": None,
        "breach_threshold": float(breach_threshold),
        "utilization": None,
        "status": "not_modeled",
        "action": "Keep",
        "explanation": explanation,
    }


def evaluate_factor_limits(factor_analytics: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    limits = config or load_risk_limits()
    factor_limits = limits["factor_limits"]
    exposure = factor_analytics.get("portfolio_factor_exposure_current", {})
    changes = factor_analytics.get("portfolio_factor_change", {})
    checks = []
    for factor, threshold in factor_limits.items():
        if factor.startswith("max_") or factor == "cash_review_threshold":
            continue
        if factor not in exposure:
            checks.append(
                _factor_not_modeled(
                    f"FACTOR_{factor.upper()}",
                    factor,
                    threshold,
                    (
                        f"Portfolio {factor} proxy loading is absent from the current weighted proxy model; "
                        "not treated as zero exposure."
                    ),
                )
            )
            continue
        checks.append(
            evaluate_max_limit(
                f"FACTOR_{factor.upper()}",
                "portfolio_factor",
                factor,
                exposure[factor],
                threshold,
                "Reduce or hedge factor exposure",
                f"Portfolio {factor} proxy exposure versus configured factor budget.",
            )
        )
    concentration = factor_analytics.get("portfolio_factor_concentration_current", {})
    checks.append(
        evaluate_max_limit(
            "FACTOR_HERFINDAHL",
            "portfolio_factor",
            "factor_herfindahl",
            concentration.get("herfindahl_abs_exposure", 0.0),
            factor_limits["max_factor_herfindahl"],
            "Diversify factor exposure",
            "Absolute factor exposure concentration versus configured Herfindahl limit.",
        )
    )
    max_change = max((abs(float(value)) for value in changes.values()), default=0.0)
    checks.append(
        evaluate_max_limit(
            "FACTOR_REBALANCE_CHANGE",
            "portfolio_factor",
            "max_factor_change_per_rebalance",
            max_change,
            factor_limits["max_factor_change_per_rebalance"],
            "Modify proposed rebalance",
            "Largest proposed factor exposure change versus rebalance factor-change limit.",
        )
    )
    checks.append(
        evaluate_max_limit(
            "FACTOR_CASH_REVIEW",
            "portfolio_factor",
            "cash_exposure",
            exposure.get("cash", 0.0),
            factor_limits["cash_review_threshold"],
            "Review idle capital and defensive allocation",
            "Cash exposure review threshold. This is a review trigger, not a market-risk breach.",
        )
    )
    return {"checks": checks, "summary": summarize_limit_status(checks)}


def evaluate_scenario_limits(factor_analytics: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    limits = config or load_risk_limits()
    scenario_limits = limits["scenario_limits"]
    checks = []
    for scenario in factor_analytics.get("scenario_shock_table", []):
        name = scenario.get("scenario")
        if name not in scenario_limits:
            continue
        checks.append(
            evaluate_max_limit(
                f"SCENARIO_{_limit_id(name)}",
                "portfolio_scenario",
                name,
                scenario.get("estimated_portfolio_impact", 0.0),
                scenario_limits[name],
                "Hedge, reduce, or require scenario review",
                f"Estimated portfolio impact under {name} versus configured scenario-loss limit.",
            )
        )
    return {"checks": checks, "summary": summarize_limit_status(checks)}


def evaluate_correlation_limits(correlation_report: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    limits = config or load_risk_limits()
    correlation_limits = limits["correlation_limits"]
    summary = correlation_report.get("summary", {})
    max_pair = summary.get("max_positive_pair") or summary.get("max_pair", {})
    max_corr = max(float(max_pair.get("correlation", 0.0) or 0.0), 0.0)
    duplicate_pairs = int(summary.get("breach_count", len(correlation_report.get("breaches", []))))
    checks = [
        evaluate_max_limit(
            "CORR_MAX_PAIR",
            "portfolio_correlation",
            "max_pairwise_positive_correlation",
            max_corr,
            correlation_limits["breach_pairwise_abs_correlation"],
            "Merge, redesign, or reduce duplicate strategy exposure",
            "Highest positive pairwise strategy correlation versus duplicate-exposure limit.",
        ),
        evaluate_max_limit(
            "CORR_DUPLICATE_PAIRS",
            "portfolio_correlation",
            "duplicate_exposure_pair_count",
            duplicate_pairs,
            correlation_limits["max_duplicate_exposure_pairs"],
            "Block allocation to duplicate strategy exposure",
            "Number of strategy pairs breaching the duplicate-exposure correlation limit.",
        ),
    ]
    return {"checks": checks, "summary": summarize_limit_status(checks)}


def evaluate_rebalance_limits(allocation: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    limits = config or load_risk_limits()
    rebalance_limits = limits["rebalance_limits"]
    changes = allocation.get("weight_changes", {})
    max_change = max((abs(float(value)) for value in changes.values()), default=0.0)
    cost = float(allocation.get("estimated_transaction_cost", 0.0))
    capital = float(allocation.get("capital", 0.0))
    cost_bps = cost / capital * 10_000 if capital else 0.0
    checks = [
        evaluate_max_limit(
            "REBAL_TURNOVER",
            "rebalance",
            "turnover",
            allocation.get("turnover", 0.0),
            rebalance_limits["max_turnover"],
            "Modify proposed rebalance",
            "Total proposed rebalance turnover versus configured limit.",
        ),
        evaluate_max_limit(
            "REBAL_COST_USD",
            "rebalance",
            "transaction_cost_dollars",
            cost,
            rebalance_limits["max_transaction_cost_dollars"],
            "Modify proposed rebalance",
            "Estimated transaction cost dollars versus rebalance cost budget.",
        ),
        evaluate_max_limit(
            "REBAL_COST_BPS",
            "rebalance",
            "transaction_cost_bps",
            cost_bps,
            rebalance_limits["max_transaction_cost_bps"],
            "Modify proposed rebalance",
            "Estimated transaction cost in bps versus rebalance cost budget.",
        ),
        evaluate_max_limit(
            "REBAL_MAX_WEIGHT_CHANGE",
            "rebalance",
            "max_single_weight_change",
            max_change,
            rebalance_limits["max_single_weight_change"],
            "Modify proposed rebalance",
            "Largest proposed strategy weight change versus configured limit.",
        ),
    ]
    return {"checks": checks, "summary": summarize_limit_status(checks)}


def evaluate_evidence_limits(strategy: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    limits = config or load_risk_limits()
    evidence_limits = limits["evidence_limits"]
    evidence = strategy.get("backtest_evidence", {})
    wfo = strategy.get("walk_forward", {})
    checks = [
        _boolean_limit(
            f"{strategy['strategy_id']}_EVIDENCE_BACKTEST",
            strategy["strategy_id"],
            "backtest_evidence_attached",
            evidence.get("status") in {"attached", "complete"},
            "Research Hold",
            "Backtest evidence must be attached before formal allocation.",
        ),
        _boolean_limit(
            f"{strategy['strategy_id']}_EVIDENCE_WFO",
            strategy["strategy_id"],
            "walk_forward_complete",
            wfo.get("status") == "complete",
            "Research Hold",
            "Walk-forward evidence must be complete before formal allocation.",
        ),
        _boolean_limit(
            f"{strategy['strategy_id']}_EVIDENCE_COST",
            strategy["strategy_id"],
            "transaction_cost_included",
            bool(evidence.get("transaction_cost_included")),
            "Research Hold",
            "Transaction cost must be included in strategy evidence.",
        ),
        _boolean_limit(
            f"{strategy['strategy_id']}_EVIDENCE_FAILURE_MODES",
            strategy["strategy_id"],
            "failure_modes_attached",
            bool(strategy.get("failure_modes")),
            "Research Hold",
            "Failure modes must be documented before formal allocation.",
        ),
    ]
    return {"checks": checks, "summary": summarize_limit_status(checks), "policy": evidence_limits}


def summarize_limit_status(checks: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"ok": 0, "watch": 0, "warning": 0, "breach": 0}
    for check in checks:
        status = check.get("status")
        if status not in summary:
            continue
        summary[status] += 1
    return summary


def worst_status(checks: list[dict[str, Any]]) -> str:
    order = {"ok": 0, "watch": 1, "warning": 2, "breach": 3}
    evaluated = [
        check["status"]
        for check in checks
        if check.get("status") not in {"not_evaluated", "not_modeled"}
    ]
    if not evaluated:
        return "ok"
    return max(evaluated, key=lambda value: order[value])


def _boolean_limit(limit_id: str, scope: str, metric: str, passed: bool, action: str, explanation: str) -> dict[str, Any]:
    return {
        "limit_id": limit_id,
        "scope": scope,
        "metric": metric,
        "current_value": bool(passed),
        "watch_threshold": True,
        "warning_threshold": True,
        "breach_threshold": True,
        "utilization": 0.0 if passed else 1.0,
        "status": "ok" if passed else "breach",
        "action": "Keep" if passed else action,
        "explanation": explanation,
    }


def _limit_id(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.upper()).strip("_")


def _status_from_utilization(utilization: float) -> str:
    if utilization >= 1.0:
        return "breach"
    if utilization >= 0.80:
        return "warning"
    if utilization >= 0.60:
        return "watch"
    return "ok"
