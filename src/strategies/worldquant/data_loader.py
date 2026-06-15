"""Load and pivot WorldQuant Alpha #2 long-format OHLCV into wide panels."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.strategies.worldquant.market_data import (
    OHLCV_LONG_COLUMNS,
    assess_ticker_data_quality,
    filter_usable_ohlcv,
    validate_ohlcv_long_format,
)


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    """Read a long-format OHLCV CSV and validate schema."""
    frame = pd.read_csv(path)
    return validate_ohlcv_long_format(frame)


def ohlcv_long_to_panels(
    ohlcv: pd.DataFrame,
    *,
    value_columns: tuple[str, ...] = ("open", "close", "volume", "adj_close"),
) -> dict[str, pd.DataFrame]:
    """Pivot validated long OHLCV into wide date x ticker panels."""
    if ohlcv.empty:
        return {column: pd.DataFrame() for column in value_columns}

    working = ohlcv.copy()
    working["date"] = pd.to_datetime(working["date"])
    panels: dict[str, pd.DataFrame] = {}
    for column in value_columns:
        panel = working.pivot(index="date", columns="ticker", values=column)
        panel = panel.sort_index()
        panels[column] = panel
    return panels


def assert_cached_ohlcv_covers_requested_range(
    ohlcv: pd.DataFrame,
    requested_start: str,
    requested_end: str,
) -> tuple[str, str]:
    """Fail fast when a cached OHLCV file does not span the requested backtest window."""
    if ohlcv.empty:
        raise ValueError(
            "cached OHLCV is empty for the requested date range; rerun with --refresh-data"
        )

    actual_start = pd.to_datetime(ohlcv["date"]).min().date()
    actual_end = pd.to_datetime(ohlcv["date"]).max().date()
    requested_start_date = pd.to_datetime(requested_start).date()
    requested_end_date = pd.to_datetime(requested_end).date()

    if actual_end < requested_start_date or actual_start > requested_end_date:
        raise ValueError(
            "cached OHLCV does not overlap the requested date range: "
            f"file spans {actual_start.isoformat()} to {actual_end.isoformat()}, "
            f"but requested {requested_start_date.isoformat()} to {requested_end_date.isoformat()}. "
            "Rerun with --refresh-data."
        )

    start_gap_days = (actual_start - requested_start_date).days
    end_gap_days = (requested_end_date - actual_end).days
    if start_gap_days > 7 or end_gap_days > 7:
        raise ValueError(
            "cached OHLCV does not cover the requested date range: "
            f"file spans {actual_start.isoformat()} to {actual_end.isoformat()}, "
            f"but requested {requested_start_date.isoformat()} to {requested_end_date.isoformat()}. "
            "Rerun with --refresh-data."
        )

    return actual_start.isoformat(), actual_end.isoformat()


def prepare_alpha2_market_data(
    ohlcv: pd.DataFrame,
    requested_tickers: list[str],
    *,
    min_valid_observations: int = 8,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    """Validate ticker quality, filter unusable names, and return wide panels."""
    validated = validate_ohlcv_long_format(ohlcv) if not ohlcv.empty else ohlcv.copy()
    quality_report = assess_ticker_data_quality(
        validated,
        requested_tickers,
        min_valid_observations=min_valid_observations,
    )
    usable = filter_usable_ohlcv(validated, quality_report)
    panels = ohlcv_long_to_panels(usable)
    return panels, usable, quality_report
