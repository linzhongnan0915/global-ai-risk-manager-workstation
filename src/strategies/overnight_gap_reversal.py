"""C2A2_004 overnight-gap reversal baseline."""

from __future__ import annotations

import pandas as pd

from src.strategies.strategy_factory import StrategyContext, StrategySpec


def overnight_gap_reversal_score(context: StrategyContext) -> pd.DataFrame:
    """Higher scores are larger negative overnight gaps to buy."""
    gap = context.panels["open"].div(context.panels["adj_close"].shift(1)).sub(1.0)
    return -gap


SPEC = StrategySpec(
    strategy_id="C2A2_004",
    version="c2a2_004_overnight_gap_reversal_baseline_v1",
    name="Equity Overnight-Gap Reversal With Liquidity Controls",
    hypothesis="Large overnight gaps may partially reverse when driven by temporary attention or liquidity shocks.",
    signal_function=overnight_gap_reversal_score,
    rebalance_every=1,
)
