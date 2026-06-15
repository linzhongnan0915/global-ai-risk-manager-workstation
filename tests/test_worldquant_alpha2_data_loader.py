"""Tests for Alpha #2 OHLCV loader cache validation."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.worldquant.data_loader import assert_cached_ohlcv_covers_requested_range
from src.strategies.worldquant.market_data import OHLCV_LONG_COLUMNS


def _ohlcv_for_range(start: str, end: str) -> pd.DataFrame:
    dates = pd.bdate_range(start, end, freq="B")
    rows = []
    for day in dates:
        rows.append(
            {
                "date": day.date().isoformat(),
                "ticker": "AAA",
                "provider_symbol": "AAA",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "adj_close": 10.4,
                "volume": 1000.0,
                "source": "test",
            }
        )
    return pd.DataFrame(rows, columns=OHLCV_LONG_COLUMNS)


def test_cached_range_validation_passes_when_file_covers_request():
    ohlcv = _ohlcv_for_range("2024-01-02", "2024-03-28")
    actual_start, actual_end = assert_cached_ohlcv_covers_requested_range(
        ohlcv,
        "2024-01-01",
        "2024-03-31",
    )
    assert actual_start <= "2024-01-02"
    assert actual_end >= "2024-03-28"


def test_cached_range_validation_fails_when_file_is_too_narrow():
    ohlcv = _ohlcv_for_range("2024-01-02", "2024-01-31")
    with pytest.raises(ValueError, match="cached OHLCV does not cover"):
        assert_cached_ohlcv_covers_requested_range(
            ohlcv,
            "2024-01-01",
            "2024-03-31",
        )
