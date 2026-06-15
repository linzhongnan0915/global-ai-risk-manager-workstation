"""C2B2_004 realized-skewness cross-sectional baseline."""

from __future__ import annotations

import pandas as pd

from src.strategies.strategy_factory import StrategyContext, StrategySpec


def realized_skewness_score(context: StrategyContext) -> pd.DataFrame:
    """Long negative realized skew as crash-risk compensation; short positive skew."""
    return -context.daily_returns.rolling(60, min_periods=60).skew()


SPEC = StrategySpec(
    strategy_id="C2B2_004", version="c2b2_004_realized_skewness_v1",
    name="Realized-Skewness Cross-Section",
    hypothesis="Negative-skew stocks may earn compensation while lottery-like positive skew is overpaid.",
    signal_function=realized_skewness_score, rebalance_every=20,
)
