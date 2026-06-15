"""C3A1_001..017 fixed-direction US-equity signals for the rapid 20+1 research set."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategies.strategy_factory import StrategyContext

_SPY_RETURN: pd.Series | None = None


def set_spy_return(series: pd.Series) -> None:
    global _SPY_RETURN
    _SPY_RETURN = series.sort_index()


def _aligned_spy(context: StrategyContext) -> pd.Series:
    if _SPY_RETURN is None:
        return context.market_return
    return _SPY_RETURN.reindex(context.daily_returns.index).fillna(0.0)


def _dollar_volume(context: StrategyContext) -> pd.DataFrame:
    return context.panels["close"].mul(context.panels["volume"])


def _momentum_12_1(close: pd.DataFrame) -> pd.DataFrame:
    lagged = close.shift(21)
    base = close.shift(252)
    return lagged.div(base).sub(1.0)


def _rolling_beta_to_spy(returns: pd.DataFrame, spy: pd.Series, window: int) -> pd.DataFrame:
    spy = spy.reindex(returns.index)
    var = spy.rolling(window, min_periods=window).var().shift(1)
    beta = returns.rolling(window, min_periods=window).cov(spy).div(var, axis=0)
    return beta


def residual_momentum_12_1(context: StrategyContext) -> pd.DataFrame:
    spy = _aligned_spy(context)
    residual = context.daily_returns.sub(_rolling_beta_to_spy(context.daily_returns, spy, 252).mul(spy, axis=0))
    return residual.shift(21).rolling(232, min_periods=232).sum()


def relative_strength_12_1(context: StrategyContext) -> pd.DataFrame:
    return _momentum_12_1(context.panels["adj_close"])


def relative_strength_6_1(context: StrategyContext) -> pd.DataFrame:
    close = context.panels["adj_close"]
    return close.shift(21).div(close.shift(126)).sub(1.0)


def volatility_adjusted_momentum(context: StrategyContext) -> pd.DataFrame:
    mom = _momentum_12_1(context.panels["adj_close"])
    vol = context.daily_returns.rolling(63, min_periods=63).std().shift(1)
    return mom.div(vol.replace(0, np.nan))


def trend_quality(context: StrategyContext) -> pd.DataFrame:
    close = context.panels["adj_close"]
    log_close = np.log(close.replace(0, np.nan))
    slope = log_close.sub(log_close.shift(126)).div(126.0)
    resid_vol = context.daily_returns.rolling(126, min_periods=126).std().shift(1)
    return slope.div(resid_vol.replace(0, np.nan))


def breakout_persistence(context: StrategyContext) -> pd.DataFrame:
    high = context.panels["high"].rolling(252, min_periods=252).max().shift(1)
    return context.panels["close"].div(high.replace(0, np.nan))


def downside_beta(context: StrategyContext) -> pd.DataFrame:
    spy = _aligned_spy(context)
    downside_market = spy.where(spy < 0.0, 0.0)
    downside_returns = context.daily_returns.where(spy.lt(0.0), 0.0)
    covariance = downside_returns.mul(downside_market, axis=0).rolling(252, min_periods=252).mean()
    variance = downside_market.pow(2).rolling(252, min_periods=252).mean()
    beta = covariance.div(variance, axis=0)
    return -beta.shift(1)


def low_downside_volatility(context: StrategyContext) -> pd.DataFrame:
    negative = context.daily_returns.clip(upper=0)
    semi = negative.pow(2).rolling(126, min_periods=126).mean().pow(0.5).shift(1)
    return -semi


def low_rolling_drawdown(context: StrategyContext) -> pd.DataFrame:
    close = context.panels["adj_close"]
    rolling_max = close.rolling(126, min_periods=126).max()
    drawdown = close.div(rolling_max).sub(1.0)
    return drawdown.rolling(126, min_periods=126).min().shift(1)


def low_tail_loss(context: StrategyContext) -> pd.DataFrame:
    def _tail_mean(series: pd.Series) -> float:
        clean = series.dropna()
        if len(clean) < 20:
            return np.nan
        cutoff = max(1, int(np.floor(len(clean) * 0.05)))
        return float(clean.nsmallest(cutoff).mean())

    tail = context.daily_returns.rolling(126, min_periods=126).apply(_tail_mean, raw=False)
    return tail.shift(1)


def low_max_effect(context: StrategyContext) -> pd.DataFrame:
    return -context.daily_returns.rolling(21, min_periods=21).max().shift(1)


def stable_dollar_volume(context: StrategyContext) -> pd.DataFrame:
    dv = _dollar_volume(context)
    mean = dv.rolling(63, min_periods=63).mean().shift(1)
    std = dv.rolling(63, min_periods=63).std().shift(1)
    cov = std.div(mean.replace(0, np.nan))
    return -cov


def low_amihud_illiquidity(context: StrategyContext) -> pd.DataFrame:
    dv = _dollar_volume(context).replace(0, np.nan)
    ratio = context.daily_returns.abs().div(dv)
    illiq = ratio.rolling(63, min_periods=63).mean().shift(1)
    return -np.log1p(illiq.clip(lower=0))


def improving_liquidity(context: StrategyContext) -> pd.DataFrame:
    log_dv = np.log1p(_dollar_volume(context))
    recent = log_dv.rolling(63, min_periods=63).mean()
    prior = log_dv.shift(63).rolling(63, min_periods=63).mean()
    return recent.sub(prior).shift(1)


def price_efficiency(context: StrategyContext) -> pd.DataFrame:
    close = context.panels["adj_close"]
    total = close.div(close.shift(126)).sub(1.0).abs()
    path = context.daily_returns.abs().rolling(126, min_periods=126).sum().shift(1)
    efficiency = total.div(path.replace(0, np.nan))
    direction = np.sign(close.div(close.shift(126)).sub(1.0))
    return efficiency.mul(direction)


def volume_confirmed_trend(context: StrategyContext) -> pd.DataFrame:
    close_mom = context.panels["adj_close"].div(context.panels["adj_close"].shift(63)).sub(1.0)
    dv = _dollar_volume(context)
    vol_confirm = dv.rolling(21, min_periods=21).mean().div(
        dv.shift(21).rolling(21, min_periods=21).mean().replace(0, np.nan)
    )
    return close_mom.mul(vol_confirm).shift(1)


def low_gap_risk(context: StrategyContext) -> pd.DataFrame:
    gap = context.panels["open"].div(context.panels["close"].shift(1)).sub(1.0)
    gap_vol = gap.rolling(63, min_periods=63).std().shift(1)
    return -gap_vol
