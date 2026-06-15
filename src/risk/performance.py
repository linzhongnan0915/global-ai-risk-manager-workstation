"""Performance and drawdown metrics for strategy and portfolio returns."""

from __future__ import annotations

import math
from statistics import mean, stdev
from typing import Iterable


TRADING_DAYS_PER_YEAR = 252


def _as_returns(returns: Iterable[float]) -> list[float]:
    values = [float(item) for item in returns]
    if not values:
        raise ValueError("returns must not be empty")
    return values


def volatility(returns: Iterable[float], periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    values = _as_returns(returns)
    if len(values) < 2:
        return 0.0
    return stdev(values) * math.sqrt(periods_per_year)


def sharpe_ratio(
    returns: Iterable[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    values = _as_returns(returns)
    if len(values) < 2:
        return 0.0
    period_rf = risk_free_rate / periods_per_year
    excess = [value - period_rf for value in values]
    excess_std = stdev(excess)
    if excess_std == 0:
        return 0.0
    return mean(excess) / excess_std * math.sqrt(periods_per_year)


def cumulative_returns(returns: Iterable[float]) -> list[float]:
    values = _as_returns(returns)
    wealth = 1.0
    cumulative = []
    for value in values:
        wealth *= 1.0 + value
        cumulative.append(wealth - 1.0)
    return cumulative


def drawdown_series(returns: Iterable[float]) -> list[float]:
    values = _as_returns(returns)
    wealth = 1.0
    peak = 1.0
    drawdowns = []
    for value in values:
        wealth *= 1.0 + value
        peak = max(peak, wealth)
        drawdowns.append((wealth / peak) - 1.0)
    return drawdowns


def max_drawdown(returns: Iterable[float]) -> float:
    return min(drawdown_series(returns))

