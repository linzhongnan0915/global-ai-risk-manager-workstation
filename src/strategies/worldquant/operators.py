"""Reusable WorldQuant-style panel operators for formulaic alpha research."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _validate_panel(values: pd.DataFrame, *, name: str = "values") -> None:
    if not isinstance(values, pd.DataFrame):
        raise TypeError(f"{name} must be a pandas DataFrame")
    if values.columns.duplicated().any():
        raise ValueError(f"{name} has duplicate column labels")
    if values.index.duplicated().any():
        raise ValueError(f"{name} has duplicate index labels")
    if not values.index.is_monotonic_increasing:
        raise ValueError(f"{name} index must be chronologically increasing")


def _validate_positive_int(value: int, *, param_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{param_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{param_name} must be a positive integer")


def _validate_aligned_panels(left: pd.DataFrame, right: pd.DataFrame) -> None:
    if not left.index.equals(right.index):
        raise ValueError("left and right must have identical indexes")
    if not left.columns.equals(right.columns):
        raise ValueError("left and right must have identical columns")


def log_safe(values: pd.DataFrame) -> pd.DataFrame:
    """Natural log of a wide price/volume panel, ticker by ticker.

    What it does
    ------------
    Applies ``ln(x)`` to each cell. This is the first step for many volume-based
    alphas such as ``log(volume)``.

    Axis
    ----
    Element-wise. No cross-ticker or cross-date aggregation.

    Inputs / outputs
    ----------------
    Input: wide DataFrame, index = dates, columns = tickers.
    Output: same shape; non-positive or invalid inputs become NaN.
    """
    _validate_panel(values)
    raw = values.astype(float).to_numpy(copy=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        logged = np.log(raw)
    invalid = (~np.isfinite(raw)) | (raw <= 0)
    logged[invalid] = np.nan
    return pd.DataFrame(logged, index=values.index, columns=values.columns)


def delta_ts(values: pd.DataFrame, periods: int) -> pd.DataFrame:
    """Time-series difference for each ticker column.

    What it does
    ------------
    Computes ``x[t] - x[t - periods]`` separately for every ticker.

    Axis
    ----
    Down rows (time) within each column. Tickers never interact.

    Inputs / outputs
    ----------------
    The first ``periods`` rows are NaN because the lagged value is unavailable.
    """
    _validate_panel(values)
    _validate_positive_int(periods, param_name="periods")
    return values.diff(periods=periods)


def rank_cs(values: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional percentile rank on each date.

    What it does
    ------------
    On every date row, ranks all tickers relative to each other and converts
    the rank to a percentile in ``[0, 1]``. Ties receive the average rank.

    Axis
    ----
    **Across columns (tickers) on each date row.** This is *not* a time-series
    rank. Do not confuse ``axis=1`` (cross-section) with ranking a ticker's
    own history down the rows.

    Inputs / outputs
    ----------------
    NaN values stay NaN and are excluded from the ranking denominator on that
    date, following pandas ``rank`` behavior.
    """
    _validate_panel(values)
    return values.rank(axis=1, method="average", pct=True, na_option="keep")


def correlation_ts(left: pd.DataFrame, right: pd.DataFrame, window: int) -> pd.DataFrame:
    """Rolling time-series correlation between two aligned panels.

    What it does
    ------------
    For each ticker, computes the Pearson correlation between ``left`` and
    ``right`` over the previous ``window`` observations on that ticker only.

    Axis
    ----
    Down rows (time) within each matched ticker column pair. Tickers never mix.

    Inputs / outputs
    ----------------
    The first ``window - 1`` rows are NaN because fewer than ``window`` points
    are available. ``left`` and ``right`` must share the same dates and tickers.
    """
    _validate_panel(left, name="left")
    _validate_panel(right, name="right")
    _validate_positive_int(window, param_name="window")
    _validate_aligned_panels(left, right)

    output = pd.DataFrame(index=left.index, columns=left.columns, dtype=float)
    for ticker in left.columns:
        output[ticker] = left[ticker].rolling(window=window).corr(right[ticker])
    output = output.replace([np.inf, -np.inf],np.nan,)
    return output
