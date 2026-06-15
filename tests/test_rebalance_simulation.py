import math

from src.allocation.rebalance_simulation import simulate_rebalance
from src.risk.engine import historical_var, expected_shortfall, weighted_portfolio_returns
from src.risk.transaction_cost import TransactionCostModel


def _strategy_row(strategy_id: str, eligible: bool = True, risk_status: str = "ok") -> dict:
    return {
        "strategy_id": strategy_id,
        "name": strategy_id,
        "allocation_eligibility": {"eligible": eligible},
        "risk_status": risk_status,
        "factor_exposure": {
            "latest": {
                "equity_beta": 0.20 if strategy_id == "A" else 0.05,
                "credit_spread": 0.02,
            }
        },
    }


def test_simulation_matches_portfolio_risk_engine_sign_conventions():
    returns = {
        "A": [0.01, -0.02, 0.005, -0.015, 0.002],
        "B": [0.004, -0.006, 0.003, -0.004, 0.001],
    }
    current = {"A": 0.5, "B": 0.5}
    target = {"A": 0.4, "B": 0.6}
    rows = [_strategy_row("A"), _strategy_row("B")]
    result = simulate_rebalance(returns, rows, current, target, capital=1_000_000)

    portfolio_returns = weighted_portfolio_returns(returns, target)
    assert math.isclose(
        result["metrics_after"]["portfolio_var_99"],
        historical_var(portfolio_returns, 0.99),
        rel_tol=1e-9,
    )
    assert math.isclose(
        result["metrics_after"]["portfolio_expected_shortfall_95"],
        expected_shortfall(portfolio_returns, 0.95),
        rel_tol=1e-9,
    )
    assert result["metrics_after"]["portfolio_var_99"] >= 0
    assert result["metrics_after"]["portfolio_expected_shortfall_95"] >= 0


def test_transaction_cost_uses_five_bps_per_side():
    returns = {"A": [0.0, 0.0], "B": [0.0, 0.0]}
    current = {"A": 0.5, "B": 0.5}
    target = {"A": 0.6, "B": 0.4}
    rows = [_strategy_row("A"), _strategy_row("B")]
    result = simulate_rebalance(returns, rows, current, target, capital=1_000_000)
    model = TransactionCostModel()
    expected = model.rebalance_cost(current, target, 1_000_000)
    assert math.isclose(result["estimated_transaction_cost"], expected, rel_tol=1e-9)
    assert math.isclose(result["turnover"], 0.2, rel_tol=1e-9)


def test_research_only_strategy_allocation_is_blocked():
    returns = {"A": [0.01], "B": [0.01]}
    current = {"A": 1.0, "B": 0.0}
    target = {"A": 0.5, "B": 0.5}
    rows = [_strategy_row("A"), _strategy_row("B", eligible=False)]
    result = simulate_rebalance(returns, rows, current, target, capital=1_000_000)
    blocked = [check for check in result["checks"] if check["status"] == "breach" and "Research-only" in check["text"]]
    assert blocked


def test_factor_exposure_before_and_after_differ_when_weights_change():
    returns = {"A": [0.01, -0.01], "B": [0.02, -0.02]}
    current = {"A": 0.9, "B": 0.1}
    target = {"A": 0.1, "B": 0.9}
    rows = [_strategy_row("A"), _strategy_row("B")]
    result = simulate_rebalance(returns, rows, current, target, capital=1_000_000)

    before = result["factor_exposure_before"]["equity_beta"]
    after = result["factor_exposure_after"]["equity_beta"]
    assert before != after
    assert before > after


def test_underinvestment_does_not_crash_and_reports_cash():
    returns = {"A": [0.01, 0.02]}
    current = {"A": 0.5}
    target = {"A": 0.4}
    rows = [_strategy_row("A")]
    result = simulate_rebalance(returns, rows, current, target, capital=1_000_000)

    assert result["cash_weight"] == 0.6
    invested = next(check for check in result["checks"] if check["metric"] == "Invested weight")
    assert invested["status"] in {"ok", "watch"}
    assert result["metrics_after"]["portfolio_sharpe"] is not None


def test_over_invested_weights_trigger_breach_check():
    returns = {"A": [0.01]}
    current = {"A": 1.0}
    target = {"A": 1.1}
    rows = [_strategy_row("A")]
    result = simulate_rebalance(returns, rows, current, target, capital=1_000_000)
    invested = next(check for check in result["checks"] if check["metric"] == "Invested weight")
    assert invested["status"] == "breach"
