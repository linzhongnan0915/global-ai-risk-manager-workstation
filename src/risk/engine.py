"""Portfolio risk engine skeleton."""

from __future__ import annotations

from statistics import mean
from typing import Iterable, Mapping

from src.portfolio.ledger import validate_weights
from src.risk.performance import max_drawdown, sharpe_ratio, volatility


def weighted_portfolio_returns(
    strategy_returns: Mapping[str, Iterable[float]],
    weights: Mapping[str, float],
    *,
    allow_residual_cash: bool = False,
) -> list[float]:
    total = sum(float(value) for value in weights.values())
    if total > 1.0 + 1e-8:
        raise ValueError(f"portfolio weights cannot exceed 1.0, got {total:.10f}")
    if not allow_residual_cash:
        validate_weights(weights)
    series = {key: list(values) for key, values in strategy_returns.items() if key in weights}
    if not series:
        raise ValueError("strategy_returns must include at least one weighted strategy")
    lengths = {len(values) for values in series.values()}
    if len(lengths) != 1:
        raise ValueError("all strategy return series must have equal length")
    periods = lengths.pop()
    return [sum(weights[key] * series[key][i] for key in series) for i in range(periods)]


def historical_var(returns: Iterable[float], confidence: float = 0.99) -> float:
    values = sorted(float(value) for value in returns)
    if not values:
        raise ValueError("returns must not be empty")
    index = max(0, int((1.0 - confidence) * len(values)) - 1)
    return abs(values[index])


def expected_shortfall(returns: Iterable[float], confidence: float = 0.95) -> float:
    values = sorted(float(value) for value in returns)
    if not values:
        raise ValueError("returns must not be empty")
    cutoff = max(1, int((1.0 - confidence) * len(values)))
    return abs(mean(values[:cutoff]))


def portfolio_risk_summary(
    strategy_returns: Mapping[str, Iterable[float]],
    weights: Mapping[str, float],
    *,
    allow_residual_cash: bool = False,
) -> dict[str, float]:
    returns = weighted_portfolio_returns(strategy_returns, weights, allow_residual_cash=allow_residual_cash)
    return {
        "portfolio_sharpe": sharpe_ratio(returns),
        "portfolio_volatility": volatility(returns),
        "portfolio_var_99": historical_var(returns, 0.99),
        "portfolio_expected_shortfall_95": expected_shortfall(returns, 0.95),
        "portfolio_max_drawdown": max_drawdown(returns),
    }

