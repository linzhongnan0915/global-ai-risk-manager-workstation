"""C2B2_003 downside-beta defensive spread baseline."""

from __future__ import annotations

import pandas as pd

from src.strategies.strategy_factory import StrategyContext, StrategySpec


def downside_beta_defensive_score(context: StrategyContext) -> pd.DataFrame:
    """Higher scores identify lower trailing sensitivity on negative-market days."""
    downside_market = context.market_return.where(context.market_return < 0.0, 0.0)
    downside_returns = context.daily_returns.where(context.market_return.lt(0.0), 0.0)
    covariance = downside_returns.mul(downside_market, axis=0).rolling(60, min_periods=60).mean()
    variance = downside_market.pow(2).rolling(60, min_periods=60).mean()
    beta = covariance.div(variance, axis=0)
    return -beta.shift(1)


SPEC = StrategySpec(
    strategy_id="C2B2_003", version="c2b2_003_downside_beta_defensive_v1",
    name="Downside-Beta Defensive Spread",
    hypothesis="Stocks with high downside-market sensitivity may be overpriced by risk-seeking demand.",
    signal_function=downside_beta_defensive_score, rebalance_every=20,
)
