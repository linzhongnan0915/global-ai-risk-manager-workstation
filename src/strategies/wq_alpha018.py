"""Locked WQ Alpha 018 formula and accepted research metadata."""

from __future__ import annotations

import pandas as pd

from src.strategies.strategy_factory import StrategyContext, StrategySpec
from src.strategies.worldquant.operators import correlation_ts, rank_cs

STRATEGY_ID = "WQ_ALPHA_018"
RESEARCH_SOURCE_COMMIT = "9d18a8651fb2c6d4b919d72c836cf2d7ee99c7a8"
FORMULA = "-rank(stddev(abs(close-open),5)+(close-open)+correlation(close,open,10))"
RATIONALE = "Prefer lower intraday range/volatility and weaker close-open correlation."
LIMITATIONS = (
    "Mixes differently scaled raw components as in the source formula; "
    "CURRENT_LISTED_DIAGNOSTIC and SURVIVORSHIP_BIAS_PRESENT."
)
RESEARCH_METRICS = {
    "net_cumulative_return": 0.38972315908099886,
    "net_sharpe": 0.523461244769271,
    "preliminary_oos_net_return": 0.1145301575744988,
    "preliminary_oos_sharpe": 0.5777065418216021,
    "double_cost_net_return": 0.2917686379376305,
    "delayed_execution_net_return": 0.31838673914575866,
    "maximum_active_correlation": 0.1368299858771812,
    "marginal_combined_portfolio_sharpe": 0.055773327657146154,
}


def wq_alpha_018_score(context: StrategyContext) -> pd.DataFrame:
    """Compute the locked formula from information available before execution."""
    open_ = context.panels["open"].shift(1)
    close = context.panels["close"].shift(1)
    close_open = close - open_
    return -rank_cs(
        close_open.abs().rolling(5, min_periods=5).std()
        + close_open
        + correlation_ts(close, open_, 10)
    )


WQ_ALPHA_018_SPEC = StrategySpec(
    STRATEGY_ID,
    "wq_alpha_018_locked_v1",
    "WQ Alpha 018",
    RATIONALE,
    wq_alpha_018_score,
    20,
    min_cross_section=100,
)
