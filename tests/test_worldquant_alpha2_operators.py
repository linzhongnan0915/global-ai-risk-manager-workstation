"""Unit tests for WorldQuant panel operators (Phase 1A)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategies.worldquant.operators import (
    correlation_ts,
    delta_ts,
    log_safe,
    rank_cs,
)

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE"]


def _dates(n: int = 12) -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-02", periods=n, freq="B")


def _panel(values_by_ticker: dict[str, list[float]]) -> pd.DataFrame:
    index = _dates(len(next(iter(values_by_ticker.values()))))
    return pd.DataFrame(values_by_ticker, index=index)


def test_log_safe_known_values_and_invalid_inputs():
    panel = _panel(
        {
            "AAA": [1.0, np.e, 10.0, 0.0, -2.0, np.nan, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0],
            "BBB": [2.0] * 12,
            "CCC": [3.0] * 12,
            "DDD": [4.0] * 12,
            "EEE": [5.0] * 12,
        }
    )
    original = panel.copy(deep=True)
    result = log_safe(panel)

    assert panel.equals(original)
    assert result.loc[_dates()[0], "AAA"] == pytest.approx(0.0)
    assert result.loc[_dates()[1], "AAA"] == pytest.approx(1.0)
    assert result.loc[_dates()[2], "AAA"] == pytest.approx(np.log(10.0))
    assert np.isnan(result.loc[_dates()[3], "AAA"])
    assert np.isnan(result.loc[_dates()[4], "AAA"])
    assert np.isnan(result.loc[_dates()[5], "AAA"])
    assert result.loc[_dates()[1], "BBB"] == pytest.approx(np.log(2.0))


def test_delta_ts_two_day_difference_and_warmup():
    panel = _panel(
        {
            "AAA": [1.0, 3.0, 6.0, 10.0, 15.0, 21.0, 28.0, 36.0, 45.0, 55.0, 66.0, 78.0],
            "BBB": [10.0] * 12,
            "CCC": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0],
            "DDD": [5.0] * 12,
            "EEE": [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 1024.0, 2048.0, 4096.0],
        }
    )
    result = delta_ts(panel, periods=2)

    assert np.isnan(result.iloc[0]).all()
    assert np.isnan(result.iloc[1]).all()
    assert result.loc[_dates()[2], "AAA"] == pytest.approx(5.0)
    assert result.loc[_dates()[2], "BBB"] == pytest.approx(0.0)
    assert result.loc[_dates()[3], "CCC"] == pytest.approx(2.0)
    assert result.loc[_dates()[5], "EEE"] == pytest.approx(48.0)  # 64 - 16


def test_rank_cs_cross_section_ties_and_nan():
    index = _dates(3)
    panel = pd.DataFrame(
        {
            "AAA": [10.0, 20.0, np.nan],
            "BBB": [30.0, 20.0, 1.0],
            "CCC": [20.0, 20.0, 3.0],
            "DDD": [40.0, 40.0, 2.0],
            "EEE": [50.0, 10.0, 4.0],
        },
        index=index,
    )
    result = rank_cs(panel)

    expected_day0 = pd.Series([0.2, 0.6, 0.4, 0.8, 1.0], index=TICKERS)
    assert result.loc[index[0]].equals(expected_day0)

    expected_day1 = pd.Series([0.6, 0.6, 0.6, 1.0, 0.2], index=TICKERS)
    assert result.loc[index[1]].equals(expected_day1)

    assert np.isnan(result.loc[index[2], "AAA"])
    assert result.loc[index[2], "BBB"] == pytest.approx(0.25)
    assert result.loc[index[2], "DDD"] == pytest.approx(0.5)
    assert result.loc[index[2], "CCC"] == pytest.approx(0.75)
    assert result.loc[index[2], "EEE"] == pytest.approx(1.0)

    changed = panel.copy()
    changed.loc[index[1], "AAA"] = 999.0
    changed_result = rank_cs(changed)
    assert result.loc[index[0]].equals(changed_result.loc[index[0]])
    assert not result.loc[index[1]].equals(changed_result.loc[index[1]])


def test_correlation_ts_positive_negative_and_warmup():
    index = _dates(12)
    left = pd.DataFrame({ticker: np.arange(1, 13, dtype=float) for ticker in TICKERS}, index=index)
    right_pos = left.copy()
    right_neg = -left

    pos = correlation_ts(left, right_pos, window=6)
    neg = correlation_ts(left, right_neg, window=6)

    assert pos.iloc[:5].isna().all().all()
    assert neg.iloc[:5].isna().all().all()
    assert np.allclose(pos.iloc[5:].to_numpy(), 1.0, rtol=0, atol=1e-12)
    assert np.allclose(neg.iloc[5:].to_numpy(), -1.0, rtol=0, atol=1e-12)

        # Create a mixed panel to verify that each ticker is calculated independently.
    mixed = left.copy()
    mixed["AAA"] = [
        1.0, 2.0, 1.0, 2.0, 1.0, 2.0,
        1.0, 2.0, 1.0, 2.0, 1.0, 2.0,
    ]

    mixed_right = mixed.copy()
    mixed_right["AAA"] = [
        2.0, 1.0, 2.0, 1.0, 2.0, 1.0,
        2.0, 1.0, 2.0, 1.0, 2.0, 1.0,
    ]

    mixed_result = correlation_ts(
        mixed,
        mixed_right,
        window=6,
    )

    assert mixed_result.loc[
        index[5],
        "AAA",
    ] == pytest.approx(-1.0)

    for ticker in ["BBB", "CCC", "DDD", "EEE"]:
        assert mixed_result.loc[
            index[5],
            ticker,
        ] == pytest.approx(1.0)


def test_validation_rejects_duplicate_dates():
    index = pd.Index(list(_dates(3)) + [_dates(3)[-1]])
    panel = pd.DataFrame({ticker: [1.0, 2.0, 3.0, 4.0] for ticker in TICKERS}, index=index)
    with pytest.raises(ValueError, match="duplicate index"):
        log_safe(panel)
    with pytest.raises(ValueError, match="duplicate index"):
        delta_ts(panel, 2)
    with pytest.raises(ValueError, match="duplicate index"):
        rank_cs(panel)
    with pytest.raises(ValueError, match="duplicate index"):
        correlation_ts(panel, panel, 6)


def test_validation_rejects_duplicate_columns():
    panel = pd.DataFrame([[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]], index=_dates(3), columns=["AAA", "AAA"])
    with pytest.raises(ValueError, match="duplicate column"):
        log_safe(panel)


def test_validation_rejects_non_increasing_index():
    index = _dates(4)[::-1]
    panel = pd.DataFrame({ticker: [1.0, 2.0, 3.0, 4.0] for ticker in TICKERS}, index=index)
    with pytest.raises(ValueError, match="chronologically increasing"):
        delta_ts(panel, 1)


def test_validation_rejects_mismatched_indexes_and_columns():
    left = _panel({ticker: [float(i) for i in range(12)] for ticker in TICKERS})
    right_index = left.copy()
    right_index.index = left.index + pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="identical indexes"):
        correlation_ts(left, right_index, window=6)

    right_columns = left.copy()
    right_columns.columns = ["AAA", "BBB", "CCC", "DDD", "FFF"]
    with pytest.raises(ValueError, match="identical columns"):
        correlation_ts(left, right_columns, window=6)


@pytest.mark.parametrize("periods", [0, -1, 1.5, True])
def test_validation_rejects_invalid_periods(periods):
    panel = _panel({ticker: [1.0] * 12 for ticker in TICKERS})
    with pytest.raises((TypeError, ValueError)):
        delta_ts(panel, periods)


@pytest.mark.parametrize("window", [0, -3, 2.0, False])
def test_validation_rejects_invalid_window(window):
    panel = _panel({ticker: [1.0] * 12 for ticker in TICKERS})
    with pytest.raises((TypeError, ValueError)):
        correlation_ts(panel, panel, window)


def test_validation_rejects_non_dataframe_input():
    with pytest.raises(TypeError, match="DataFrame"):
        log_safe([[1, 2], [3, 4]])


def test_no_future_leakage_for_operators():
    panel = _panel(
        {
            "AAA": [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 1024.0, 2048.0],
            "BBB": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0],
            "CCC": [3.0, 6.0, 9.0, 12.0, 15.0, 18.0, 21.0, 24.0, 27.0, 30.0, 33.0, 36.0],
            "DDD": [5.0] * 12,
            "EEE": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0],
        }
    )
    cutoff = _dates()[5]

    before_log = log_safe(panel)
    before_delta = delta_ts(panel, 2)
    before_rank = rank_cs(panel)
    before_corr = correlation_ts(panel, panel * 2.0, window=6)

    changed = panel.copy()
    changed.loc[changed.index > cutoff, :] = changed.loc[changed.index > cutoff, :] * 100.0

    after_log = log_safe(changed)
    after_delta = delta_ts(changed, 2)
    after_rank = rank_cs(changed)
    after_corr = correlation_ts(changed, changed * 2.0, window=6)

    assert before_log.loc[:cutoff].equals(after_log.loc[:cutoff])
    assert before_delta.loc[:cutoff].equals(after_delta.loc[:cutoff])
    assert before_rank.loc[:cutoff].equals(after_rank.loc[:cutoff])
    assert before_corr.loc[:cutoff].equals(after_corr.loc[:cutoff])
