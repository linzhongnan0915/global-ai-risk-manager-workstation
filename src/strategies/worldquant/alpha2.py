"""WorldQuant Alpha #2 signal composition (research module)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategies.worldquant.operators import (
    _validate_aligned_panels,
    _validate_panel,
    _validate_positive_int,
    correlation_ts,
    delta_ts,
    log_safe,
    rank_cs,
)


def _validate_three_panels(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    volume: pd.DataFrame,
) -> None:
    _validate_panel(open_prices, name="open_prices")
    _validate_panel(close_prices, name="close_prices")
    _validate_panel(volume, name="volume")
    _validate_aligned_panels(open_prices, close_prices)
    _validate_aligned_panels(open_prices, volume)


def compute_intraday_return(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
) -> pd.DataFrame:
    """Intraday return from open to close for each ticker and date.

    What it does
    ------------
    Computes ``(close - open) / open`` element-wise. This is the price-change
    component used in WorldQuant Alpha #2.

    Inputs / outputs
    ----------------
    ``open_prices`` and ``close_prices`` must share the same dates and tickers.
    Non-positive or non-finite open prices produce NaN. Non-finite close prices
    also produce NaN. Inputs are not modified.
    """
    _validate_panel(open_prices, name="open_prices")
    _validate_panel(close_prices, name="close_prices")
    _validate_aligned_panels(open_prices, close_prices)

    open_values = open_prices.astype(float).to_numpy(copy=True)
    close_values = close_prices.astype(float).to_numpy(copy=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        returns = (close_values - open_values) / open_values

    invalid = (
        (~np.isfinite(open_values))
        | (~np.isfinite(close_values))
        | (open_values <= 0)
    )
    returns[invalid] = np.nan
    return pd.DataFrame(returns, index=open_prices.index, columns=open_prices.columns)


def compute_alpha2_components(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    volume: pd.DataFrame,
    *,
    delta_periods: int = 2,
    correlation_window: int = 6,
) -> dict[str, pd.DataFrame]:
    """Compute every intermediate panel and the final Alpha #2 signal.

    Formula
    -------
    ``alpha = -correlation_ts(rank_cs(delta_ts(log_safe(volume))),
                               rank_cs((close-open)/open), window)``

    All three input panels must share identical dates and ticker columns.
    NaN values are preserved; nothing is forward- or back-filled.
    """
    _validate_three_panels(open_prices, close_prices, volume)
    _validate_positive_int(delta_periods, param_name="delta_periods")
    _validate_positive_int(correlation_window, param_name="correlation_window")

    log_volume = log_safe(volume)
    volume_delta = delta_ts(log_volume, periods=delta_periods)
    volume_delta_rank = rank_cs(volume_delta)
    intraday_return = compute_intraday_return(open_prices, close_prices)
    intraday_return_rank = rank_cs(intraday_return)
    rolling_correlation = correlation_ts(
        volume_delta_rank,
        intraday_return_rank,
        window=correlation_window,
    )
    alpha = -rolling_correlation

    return {
        "log_volume": log_volume,
        "volume_delta": volume_delta,
        "volume_delta_rank": volume_delta_rank,
        "intraday_return": intraday_return,
        "intraday_return_rank": intraday_return_rank,
        "rolling_correlation": rolling_correlation,
        "alpha": alpha,
    }


def compute_alpha2(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    volume: pd.DataFrame,
    *,
    delta_periods: int = 2,
    correlation_window: int = 6,
) -> pd.DataFrame:
    """Return the final WorldQuant Alpha #2 signal panel."""
    components = compute_alpha2_components(
        open_prices,
        close_prices,
        volume,
        delta_periods=delta_periods,
        correlation_window=correlation_window,
    )
    return components["alpha"]
