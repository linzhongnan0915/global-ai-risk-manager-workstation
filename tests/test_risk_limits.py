from src.risk.limits import (
    evaluate_correlation_limits,
    evaluate_evidence_limits,
    evaluate_factor_limits,
    evaluate_max_limit,
    evaluate_min_limit,
    evaluate_monitor_min_limit,
    evaluate_rebalance_limits,
    evaluate_research_quality_limits,
    evaluate_scenario_limits,
    evaluate_strategy_limits,
    summarize_limit_status,
)


def test_max_limit_statuses():
    ok = evaluate_max_limit("x", "portfolio", "vol", 0.04, 0.12, "Reduce", "test")
    warning = evaluate_max_limit("x", "portfolio", "vol", 0.10, 0.12, "Reduce", "test")
    breach = evaluate_max_limit("x", "portfolio", "vol", 0.13, 0.12, "Reduce", "test")

    assert ok["status"] == "ok"
    assert warning["status"] == "warning"
    assert breach["status"] == "breach"


def test_min_limit_statuses():
    ok = evaluate_min_limit("x", "strategy", "sharpe", 0.50, 0.25, "Watch", "test")
    breach = evaluate_min_limit("x", "strategy", "sharpe", 0.0, 0.25, "Watch", "test")

    assert ok["status"] == "ok"
    assert breach["status"] == "breach"


def test_performance_monitor_does_not_create_hard_breach():
    warning = evaluate_monitor_min_limit("x", "strategy", "rolling_sharpe", -1.0, -0.5, "Watch", "test")

    assert warning["status"] == "warning"
    assert warning["hard_limit"] is False


def test_limit_summary_counts():
    checks = [
        {"status": "ok"},
        {"status": "ok"},
        {"status": "watch"},
        {"status": "warning"},
        {"status": "breach"},
    ]

    assert summarize_limit_status(checks) == {"ok": 2, "watch": 1, "warning": 1, "breach": 1}


def test_factor_limits_mark_absent_proxy_loadings_not_modeled():
    factors = {
        "portfolio_factor_exposure_current": {"equity_beta": 0.10},
        "portfolio_factor_change": {},
        "portfolio_factor_concentration_current": {"herfindahl_abs_exposure": 0.20},
    }
    status = evaluate_factor_limits(factors)
    by_metric = {check["metric"]: check for check in status["checks"]}
    assert by_metric["volatility"]["status"] == "not_modeled"
    assert by_metric["volatility"]["current_value"] is None
    assert by_metric["volatility"]["utilization"] is None
    assert by_metric["equity_beta"]["current_value"] == 0.10


def test_extended_limit_categories():
    factors = {
        "portfolio_factor_exposure_current": {"equity_beta": 0.20, "cash": 0.40},
        "portfolio_factor_change": {"equity_beta": 0.06},
        "portfolio_factor_concentration_current": {"herfindahl_abs_exposure": 0.40},
        "scenario_shock_table": [{"scenario": "Equity -5%", "estimated_portfolio_impact": -0.02}],
    }
    factor_status = evaluate_factor_limits(factors)
    scenario_status = evaluate_scenario_limits(factors)
    correlation_status = evaluate_correlation_limits(
        {
            "summary": {"max_pair": {"correlation": 0.85}},
            "breaches": [{"left_strategy_id": "A", "right_strategy_id": "B"}],
        }
    )
    rebalance_status = evaluate_rebalance_limits(
        {
            "weight_changes": {"A": 0.04, "B": -0.04},
            "turnover": 0.20,
            "estimated_transaction_cost": 900,
            "capital": 1_000_000,
        }
    )

    assert factor_status["summary"]["breach"] >= 1
    assert scenario_status["summary"]["breach"] >= 1
    assert correlation_status["summary"]["breach"] == 2
    assert rebalance_status["summary"]["breach"] >= 1


def test_evidence_limits_block_missing_evidence():
    status = evaluate_evidence_limits(
        {
            "strategy_id": "TEST",
            "backtest_evidence": {"status": "missing_data", "transaction_cost_included": False},
            "walk_forward": {"status": "insufficient_history"},
            "failure_modes": [],
        }
    )

    assert status["summary"]["breach"] == 4


def test_historical_drawdown_is_not_a_live_breach():
    strategy = {
        "strategy_id": "TEST",
        "proxy_metrics": {"proxy_max_drawdown": -0.60, "proxy_sharpe": 0.50},
        "risk_packet": {
            "drawdown_behavior": {"current_drawdown": -0.02},
            "time_stability": {"63d": {"latest_rolling_volatility": 0.08, "latest_rolling_sharpe": 0.70}},
        },
        "turnover": {"annualized_turnover": 2.0, "annualized_cost_drag": 0.001},
        "walk_forward": {"number_of_windows": 10, "positive_window_rate": 0.60, "average_test_sharpe": 0.30},
    }

    live = evaluate_strategy_limits(strategy)
    research = evaluate_research_quality_limits(strategy)

    assert live["summary"]["breach"] == 0
    assert research["summary"]["breach"] >= 1
