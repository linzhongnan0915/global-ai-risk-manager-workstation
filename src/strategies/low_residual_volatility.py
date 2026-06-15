"""C2A2_002 transparent low-residual-volatility baseline."""

from __future__ import annotations

import pandas as pd

from src.strategies.strategy_factory import StrategyContext, StrategySpec


def low_residual_volatility_score(context: StrategyContext) -> pd.DataFrame:
    residual = context.daily_returns.sub(context.lagged_beta.mul(context.market_return, axis=0))
    return -residual.rolling(60, min_periods=60).std()


SPEC = StrategySpec(
    strategy_id="C2A2_002",
    version="c2a2_002_low_residual_volatility_baseline_v1",
    name="Cross-Sectional Low-Residual-Volatility Equity",
    hypothesis="Low residual-risk stocks may offer better risk-adjusted returns than high residual-risk stocks.",
    signal_function=low_residual_volatility_score,
    rebalance_every=20,
    require_beta_history=True,
)
