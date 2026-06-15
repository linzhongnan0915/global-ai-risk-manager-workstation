"""C3A2 simple low-turnover US-equity signals to expand the Combined Portfolio member set."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategies.strategy_factory import StrategyContext


def short_term_reversal_5d(context: StrategyContext) -> pd.DataFrame:
    """Fade very short-term moves; long recent losers and short recent winners."""
    return -context.daily_returns.rolling(5, min_periods=5).sum().shift(1)


def low_realized_volatility_60d(context: StrategyContext) -> pd.DataFrame:
    """Long lower trailing realized volatility."""
    vol = context.daily_returns.rolling(60, min_periods=60).std().shift(1)
    return -vol


def low_market_beta_60d(context: StrategyContext) -> pd.DataFrame:
    """Long lower trailing market beta using cross-sectional market proxy."""
    market = context.market_return
    var = market.rolling(60, min_periods=60).var().shift(1)
    beta = context.daily_returns.rolling(60, min_periods=60).cov(market).div(var, axis=0)
    return -beta.shift(1)


def medium_term_reversal_22d(context: StrategyContext) -> pd.DataFrame:
    """Contrarian signal over roughly one trading month."""
    return -context.panels["adj_close"].pct_change(22, fill_method=None).shift(1)


def low_idiosyncratic_volatility_60d(context: StrategyContext) -> pd.DataFrame:
    """Long lower residual volatility after removing market component."""
    market = context.market_return
    var = market.rolling(60, min_periods=60).var().shift(1)
    beta = context.daily_returns.rolling(60, min_periods=60).cov(market).div(var, axis=0)
    residual = context.daily_returns.sub(beta.mul(market, axis=0))
    return -residual.rolling(60, min_periods=60).std().shift(1)


def distance_from_200dma(context: StrategyContext) -> pd.DataFrame:
    """Simple value proxy: long names below long-run average, short extended names."""
    ma = context.panels["adj_close"].rolling(200, min_periods=200).mean().shift(1)
    return -context.panels["close"].div(ma.replace(0, np.nan)).sub(1.0)


def low_intraday_range_volatility(context: StrategyContext) -> pd.DataFrame:
    """Long names with lower normalized high-low range."""
    range_pct = (context.panels["high"] - context.panels["low"]).div(context.panels["close"].replace(0, np.nan))
    return -range_pct.rolling(60, min_periods=60).mean().shift(1)


def slow_momentum_9_1(context: StrategyContext) -> pd.DataFrame:
    """Long stronger 9-1 momentum; short weaker momentum."""
    close = context.panels["adj_close"]
    return close.shift(21).div(close.shift(189)).sub(1.0)


def high_log_dollar_volume_63d(context: StrategyContext) -> pd.DataFrame:
    """Long higher trailing dollar volume; short lower-liquidity names."""
    dollar_volume = context.panels["close"].mul(context.panels["volume"])
    return np.log1p(dollar_volume.rolling(63, min_periods=63).mean().shift(1))
