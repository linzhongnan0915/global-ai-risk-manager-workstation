"""Portfolio return and transaction-cost helpers for Alpha #2 research."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

EXECUTION_MODE_NEXT_OPEN_TO_OPEN = "next_open_to_open"
EXECUTION_MODE_NEXT_OPEN_TO_CLOSE = "next_open_to_close"
EXECUTION_MODE_CLOSE_TO_CLOSE_LAG2 = "close_to_close_lag2"

SUPPORTED_EXECUTION_MODES = frozenset(
    {
        EXECUTION_MODE_NEXT_OPEN_TO_OPEN,
        EXECUTION_MODE_NEXT_OPEN_TO_CLOSE,
        EXECUTION_MODE_CLOSE_TO_CLOSE_LAG2,
    }
)

EXECUTION_MODE_SPECS: dict[str, dict[str, int | str]] = {
    EXECUTION_MODE_NEXT_OPEN_TO_OPEN: {
        "execution_lag": 0,
        "return_definition": "open_to_open",
    },
    EXECUTION_MODE_NEXT_OPEN_TO_CLOSE: {
        "execution_lag": 1,
        "return_definition": "open_to_close",
    },
    EXECUTION_MODE_CLOSE_TO_CLOSE_LAG2: {
        "execution_lag": 2,
        "return_definition": "close_to_close",
    },
}


@dataclass(frozen=True)
class PortfolioReturnResult:
    executed_weights: pd.DataFrame
    gross_return: pd.Series
    turnover: pd.Series
    transaction_cost: pd.Series
    net_return: pd.Series
    execution_lag: int
    return_definition: str
    hedge_weight: pd.Series | None = None
    hedge_return: pd.Series | None = None
    hedge_turnover: pd.Series | None = None
    hedge_transaction_cost: pd.Series | None = None


def validate_execution_mode(execution_mode: str) -> str:
    normalized = str(execution_mode).strip()
    if normalized not in SUPPORTED_EXECUTION_MODES:
        supported = ", ".join(sorted(SUPPORTED_EXECUTION_MODES))
        raise ValueError(f"execution_mode must be one of: {supported}")
    return normalized


def resolve_execution_spec(execution_mode: str) -> tuple[int, str]:
    normalized = validate_execution_mode(execution_mode)
    spec = EXECUTION_MODE_SPECS[normalized]
    return int(spec["execution_lag"]), str(spec["return_definition"])


def build_asset_return_panel(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    adj_close: pd.DataFrame,
    *,
    execution_mode: str,
) -> pd.DataFrame:
    """Build the asset return panel aligned to the selected execution convention."""
    normalized = validate_execution_mode(execution_mode)
    if normalized == EXECUTION_MODE_NEXT_OPEN_TO_OPEN:
        with np.errstate(divide="ignore", invalid="ignore"):
            returns = open_prices.shift(-1) / open_prices - 1.0
        returns.iloc[-1, :] = np.nan
        return returns.replace([np.inf, -np.inf], np.nan)
    if normalized == EXECUTION_MODE_NEXT_OPEN_TO_CLOSE:
        with np.errstate(divide="ignore", invalid="ignore"):
            returns = close_prices / open_prices - 1.0
        return returns.replace([np.inf, -np.inf], np.nan)
    return adj_close.pct_change(fill_method=None)


def compute_portfolio_returns_from_weights(
    target_weights: pd.DataFrame,
    asset_returns: pd.DataFrame,
    *,
    execution_lag: int,
    buy_bps: float,
    sell_bps: float,
    return_definition: str,
    hedge_weights: pd.Series | None = None,
    hedge_returns: pd.Series | None = None,
    hedge_buy_bps: float | None = None,
    hedge_sell_bps: float | None = None,
) -> PortfolioReturnResult:
    """Apply execution lag, gross PnL, symmetric turnover costs, and net PnL."""
    if execution_lag < 0:
        raise ValueError("execution_lag must be non-negative")

    executed_weights = target_weights.copy() if execution_lag == 0 else target_weights.shift(execution_lag).fillna(0.0)
    gross_return = (executed_weights * asset_returns).sum(axis=1, min_count=1)
    gross_return = gross_return.where(executed_weights.abs().sum(axis=1).ne(0), 0.0)
    hedge_weight = hedge_return = hedge_turnover = hedge_transaction_cost = None
    if (hedge_weights is None) != (hedge_returns is None):
        raise ValueError("hedge_weights and hedge_returns must be provided together")
    if hedge_weights is not None and hedge_returns is not None:
        hedge_weight = hedge_weights.reindex(target_weights.index).fillna(0.0)
        if execution_lag:
            hedge_weight = hedge_weight.shift(execution_lag).fillna(0.0)
        hedge_return = hedge_weight * hedge_returns.reindex(target_weights.index)
        gross_return = gross_return + hedge_return
        hedge_turnover = hedge_weight.diff().abs().fillna(hedge_weight.abs())
        hedge_rate = ((hedge_buy_bps if hedge_buy_bps is not None else buy_bps) + (hedge_sell_bps if hedge_sell_bps is not None else sell_bps)) / 2.0 / 10_000.0
        hedge_transaction_cost = hedge_turnover * hedge_rate
    turnover = executed_weights.diff().abs().sum(axis=1)
    turnover = turnover.fillna(executed_weights.abs().sum(axis=1))
    transaction_cost = turnover * (buy_bps + sell_bps) / 2.0 / 10_000.0
    if hedge_turnover is not None and hedge_transaction_cost is not None:
        turnover = turnover + hedge_turnover
        transaction_cost = transaction_cost + hedge_transaction_cost
    net_return = gross_return - transaction_cost

    return PortfolioReturnResult(
        executed_weights=executed_weights,
        gross_return=gross_return,
        turnover=turnover,
        transaction_cost=transaction_cost,
        net_return=net_return,
        execution_lag=execution_lag,
        return_definition=return_definition,
        hedge_weight=hedge_weight,
        hedge_return=hedge_return,
        hedge_turnover=hedge_turnover,
        hedge_transaction_cost=hedge_transaction_cost,
    )
