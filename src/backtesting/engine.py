"""Backtesting engine skeleton with net-of-cost metric hooks."""

from __future__ import annotations

from dataclasses import dataclass

from src.risk.performance import max_drawdown, sharpe_ratio, volatility
from src.risk.transaction_cost import TransactionCostModel


@dataclass(frozen=True)
class BacktestResult:
    strategy_id: str
    gross_return: float
    net_return: float
    sharpe: float
    volatility: float
    max_drawdown: float
    transaction_cost_drag: float
    validation_status: str


def run_placeholder_backtest(
    strategy_id: str,
    daily_returns: list[float],
    turnover_notional: float,
    capital: float,
    cost_model: TransactionCostModel | None = None,
) -> BacktestResult:
    model = cost_model or TransactionCostModel()
    transaction_cost = model.round_trip_cost(turnover_notional) if turnover_notional else 0.0
    cost_drag = transaction_cost / capital if capital else 0.0
    gross_return = 1.0
    for value in daily_returns:
        gross_return *= 1.0 + value
    gross_return -= 1.0
    net_returns = [value - (cost_drag / max(len(daily_returns), 1)) for value in daily_returns]
    net_return = 1.0
    for value in net_returns:
        net_return *= 1.0 + value
    net_return -= 1.0
    return BacktestResult(
        strategy_id=strategy_id,
        gross_return=gross_return,
        net_return=net_return,
        sharpe=sharpe_ratio(net_returns),
        volatility=volatility(net_returns),
        max_drawdown=max_drawdown(net_returns),
        transaction_cost_drag=cost_drag,
        validation_status="placeholder_no_live_signal",
    )

