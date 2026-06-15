"""C2A2_020 liquidity-resilience baseline."""

from __future__ import annotations

import pandas as pd

from src.strategies.strategy_factory import StrategyContext, StrategySpec


def liquidity_resilience_score(context: StrategyContext) -> pd.DataFrame:
    """Higher scores identify lower price impact during market and volume stress."""
    volume = context.panels["volume"]
    relative_volume = volume.div(volume.rolling(20, min_periods=20).mean().shift(1))
    market_scale = context.market_return.rolling(20, min_periods=20).std().shift(1)
    market_stress = context.market_return.abs().div(market_scale)
    price_impact = context.daily_returns.abs().mul(relative_volume).mul(market_stress, axis=0)
    return -price_impact.rolling(20, min_periods=20).mean()


SPEC = StrategySpec(
    strategy_id="C2A2_020",
    version="c2a2_020_liquidity_resilience_baseline_v1",
    name="Cross-Sectional Liquidity Resilience",
    hypothesis="Stocks with lower price impact during market and volume stress may exhibit a resilience premium.",
    signal_function=liquidity_resilience_score,
    rebalance_every=20,
)
