"""Unit tests for WorldQuant Alpha #2 signal composition (Phase 1B)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategies.worldquant.alpha2 import (
    compute_alpha2,
    compute_alpha2_components,
    compute_intraday_return,
)
from src.strategies.worldquant.operators import correlation_ts, delta_ts, log_safe, rank_cs

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE"]


def _dates(n: int = 12) -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-02", periods=n, freq="B")


def _synthetic_panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Deterministic OHLCV panels with 12 business dates and 5 tickers."""
    index = _dates()
    open_prices = pd.DataFrame(
        {
            "AAA": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            "BBB": [50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0],
            "CCC": [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0],
            "DDD": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            "EEE": [25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0],
        },
        index=index,
    )
    close_prices = pd.DataFrame(
        {
            "AAA": [101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0, 111.0, 112.0],
            "BBB": [49.0, 48.0, 47.0, 46.0, 45.0, 44.0, 43.0, 42.0, 41.0, 40.0, 39.0, 38.0],
            "CCC": [21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0, 30.0, 31.0, 32.0],
            "DDD": [10.5, 10.0, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.0, 5.5, 5.0],
            "EEE": [26.0, 27.0, 28.0, 29.0, 30.0, 31.0, 32.0, 33.0, 34.0, 35.0, 36.0, 37.0],
        },
        index=index,
    )
    volume = pd.DataFrame(
        {
            "AAA": [100.0, 200.0, 400.0, 800.0, 1600.0, 3200.0, 6400.0, 12800.0, 25600.0, 51200.0, 102400.0, 204800.0],
            "BBB": [50.0, 100.0, 200.0, 400.0, 800.0, 1600.0, 3200.0, 6400.0, 12800.0, 25600.0, 51200.0, 102400.0],
            "CCC": [10.0, 20.0, 40.0, 80.0, 160.0, 320.0, 640.0, 1280.0, 2560.0, 5120.0, 10240.0, 20480.0],
            "DDD": [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0, 640.0, 1280.0, 2560.0, 5120.0, 10240.0],
            "EEE": [20.0, 40.0, 80.0, 160.0, 320.0, 640.0, 1280.0, 2560.0, 5120.0, 10240.0, 20480.0, 40960.0],
        },
        index=index,
    )
    return open_prices, close_prices, volume


def _finite_alpha_panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """OHLCV panels with varying cross-sectional ranks and finite post-warmup Alpha."""
    index = _dates()
    open_prices = pd.DataFrame(
        {
            "AAA": [100.12573, 99.867895, 100.640423, 100.1049, 99.464331, 100.361595, 101.304, 100.947081, 99.296265, 98.734579, 99.376726, 100.041326],
            "BBB": [97.674969, 99.781208, 98.754089, 99.267733, 99.455741, 99.6837, 100.411631, 101.042513, 99.871465, 101.366463, 99.334805, 100.35151],
            "CCC": [100.90347, 100.094012, 99.256501, 99.078275, 99.542274, 100.220195, 98.990382, 99.790824, 99.840775, 100.540846, 100.214659, 100.355373],
            "DDD": [99.346171, 99.870386, 100.783975, 101.493431, 98.740934, 101.513924, 101.345875, 100.781311, 100.264456, 99.686077, 101.458021, 101.960258],
            "EEE": [101.801635, 101.315104, 100.35738, 98.791681, 99.995546, 100.656475, 98.711639, 100.395122, 100.429864, 100.696043, 98.815882, 99.338297],
        },
        index=index,
    )
    close_prices = pd.DataFrame(
        {
            "AAA": [98.816424, 99.092178, 100.79651, 96.143607, 100.029888, 102.25283, 100.441837, 104.04144, 100.804313, 94.893397, 97.631803, 97.766217],
            "BBB": [94.165564, 104.531627, 100.805148, 97.283149, 97.556159, 101.427197, 105.134855, 101.525542, 102.840604, 99.227259, 99.662644, 104.614456],
            "CCC": [106.121574, 104.055095, 102.268385, 101.883425, 98.409584, 104.103872, 97.692024, 98.034238, 99.347891, 102.403899, 99.987555, 102.533654],
            "DDD": [97.858439, 101.770444, 98.930254, 101.640595, 95.467496, 99.250106, 99.139426, 96.757652, 97.041361, 92.935654, 102.064364, 104.491456],
            "EEE": [102.788544, 94.704574, 105.823415, 104.798859, 96.162505, 105.723797, 99.460995, 96.190561, 103.04899, 101.855152, 100.898398, 102.832889],
        },
        index=index,
    )
    volume = pd.DataFrame(
        {
            "AAA": [1236.276467, 1253.223604, 1022.678083, 571.967845, 959.48647, 769.145608, 573.177469, 1077.535837, 829.435164, 691.058669, 687.099676, 1080.525124],
            "BBB": [1107.601585, 1396.737241, 995.825599, 1312.551928, 1420.679448, 1345.049691, 290.408828, 1368.605116, 1101.886002, 1127.131406, 1111.368225, 1114.827148],
            "CCC": [1095.824266, 892.326007, 429.50941, 967.325582, 758.880445, 1324.049024, 913.370048, 1025.042607, 745.118213, 846.81326, 996.540081, 554.387445],
            "DDD": [1090.205534, 968.178324, 644.284058, 280.53014, 1153.91564, 910.724788, 840.997476, 929.153611, 1544.942782, 985.059709, 1025.985779, 553.878139],
            "EEE": [1494.20172, 1275.246395, 1320.08046, 1014.301819, 1274.996437, 1111.284051, 1183.956723, 954.342112, 557.833616, 1308.656304, 419.512109, 928.018999],
        },
        index=index,
    )
    return open_prices, close_prices, volume


def test_components_preserve_index_and_columns():
    open_prices, close_prices, volume = _synthetic_panels()
    components = compute_alpha2_components(open_prices, close_prices, volume)

    expected_index = open_prices.index
    expected_columns = open_prices.columns
    for name, frame in components.items():
        assert frame.index.equals(expected_index), name
        assert frame.columns.equals(expected_columns), name


def test_compute_intraday_return_known_values_and_invalid_open():
    index = _dates(4)
    open_prices = pd.DataFrame(
        {"AAA": [100.0, 50.0, 0.0, -10.0], "BBB": [20.0, 20.0, 20.0, 20.0]},
        index=index,
    )
    close_prices = pd.DataFrame(
        {"AAA": [110.0, 45.0, 5.0, 12.0], "BBB": [22.0, 18.0, 24.0, 20.0]},
        index=index,
    )
    original_open = open_prices.copy(deep=True)
    original_close = close_prices.copy(deep=True)

    result = compute_intraday_return(open_prices, close_prices)

    assert open_prices.equals(original_open)
    assert close_prices.equals(original_close)
    assert result.loc[index[0], "AAA"] == pytest.approx(0.10)
    assert result.loc[index[1], "AAA"] == pytest.approx(-0.10)
    assert result.loc[index[0], "BBB"] == pytest.approx(0.10)
    assert np.isnan(result.loc[index[2], "AAA"])
    assert np.isnan(result.loc[index[3], "AAA"])


def test_composition_order_matches_operator_pipeline():
    open_prices, close_prices, volume = _synthetic_panels()
    components = compute_alpha2_components(open_prices, close_prices, volume)

    expected_log_volume = log_safe(volume)
    expected_volume_delta = delta_ts(expected_log_volume, periods=2)
    expected_volume_rank = rank_cs(expected_volume_delta)
    expected_intraday = compute_intraday_return(open_prices, close_prices)
    expected_intraday_rank = rank_cs(expected_intraday)
    expected_correlation = correlation_ts(
        expected_volume_rank,
        expected_intraday_rank,
        window=6,
    )
    expected_alpha = -expected_correlation

    pd.testing.assert_frame_equal(components["log_volume"], expected_log_volume)
    pd.testing.assert_frame_equal(components["volume_delta"], expected_volume_delta)
    pd.testing.assert_frame_equal(components["volume_delta_rank"], expected_volume_rank)
    pd.testing.assert_frame_equal(components["intraday_return"], expected_intraday)
    pd.testing.assert_frame_equal(components["intraday_return_rank"], expected_intraday_rank)
    pd.testing.assert_frame_equal(components["rolling_correlation"], expected_correlation)
    pd.testing.assert_frame_equal(components["alpha"], expected_alpha)

    date = _dates()[4]
    assert components["volume_delta_rank"].loc[date].between(0, 1).all()
    assert components["intraday_return_rank"].loc[date].between(0, 1).all()


def test_warmup_first_seven_alpha_rows_are_nan():
    open_prices, close_prices, volume = _synthetic_panels()
    alpha = compute_alpha2(open_prices, close_prices, volume)

    assert alpha.iloc[:7].isna().all().all()


def test_warmup_produces_finite_alpha_after_period():
    open_prices, close_prices, volume = _finite_alpha_panels()
    alpha = compute_alpha2(open_prices, close_prices, volume)

    assert alpha.iloc[:7].isna().all().all()
    assert np.isfinite(alpha.iloc[7:].to_numpy()).any()


def test_negative_sign_alpha_equals_negative_correlation():
    open_prices, close_prices, volume = _synthetic_panels()
    components = compute_alpha2_components(open_prices, close_prices, volume)

    pd.testing.assert_frame_equal(
        components["alpha"],
        -components["rolling_correlation"],
    )
    assert not np.isinf(components["rolling_correlation"].to_numpy()).any()
    assert not np.isinf(components["alpha"].to_numpy()).any()

    open_px, close_px, vol = _finite_alpha_panels()
    neg_components = compute_alpha2_components(open_px, close_px, vol)
    pd.testing.assert_frame_equal(
        neg_components["alpha"],
        -neg_components["rolling_correlation"],
    )
    assert not np.isinf(neg_components["rolling_correlation"].to_numpy()).any()
    assert not np.isinf(neg_components["alpha"].to_numpy()).any()

    date = _dates()[7]
    ticker = "DDD"
    corr = neg_components["rolling_correlation"].loc[date, ticker]
    alpha_val = neg_components["alpha"].loc[date, ticker]
    assert np.isfinite(corr)
    assert corr < 0
    assert np.isfinite(alpha_val)
    assert alpha_val > 0
    assert alpha_val == pytest.approx(-corr)


def test_parameter_delta_periods_changes_volume_delta():
    open_prices, close_prices, volume = _synthetic_panels()
    two = compute_alpha2_components(open_prices, close_prices, volume, delta_periods=2)
    one = compute_alpha2_components(open_prices, close_prices, volume, delta_periods=1)

    assert not two["volume_delta"].equals(one["volume_delta"])
    assert two["volume_delta"].iloc[1].isna().all()
    assert not one["volume_delta"].iloc[1].isna().all()


def test_parameter_correlation_window_changes_warmup():
    open_prices, close_prices, volume = _synthetic_panels()
    six = compute_alpha2(open_prices, close_prices, volume, correlation_window=6)
    three = compute_alpha2(open_prices, close_prices, volume, correlation_window=3)

    assert six.iloc[:7].isna().all().all()
    assert three.iloc[:7].isna().sum().sum() < six.iloc[:7].isna().sum().sum()

    first_valid_six = six.apply(pd.Series.first_valid_index)
    first_valid_three = three.apply(pd.Series.first_valid_index)
    for ticker in TICKERS:
        if pd.isna(first_valid_six[ticker]):
            assert pd.isna(first_valid_three[ticker])
        else:
            assert first_valid_three[ticker] <= first_valid_six[ticker]


def test_validation_rejects_mismatched_panels():
    open_prices, close_prices, volume = _synthetic_panels()
    bad_index = volume.copy()
    bad_index.index = volume.index + pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="identical indexes"):
        compute_alpha2_components(open_prices, close_prices, bad_index)

    bad_columns = volume.copy()
    bad_columns.columns = ["AAA", "BBB", "CCC", "DDD", "FFF"]
    with pytest.raises(ValueError, match="identical columns"):
        compute_alpha2_components(open_prices, close_prices, bad_columns)


def test_validation_rejects_duplicate_and_non_monotonic_dates():
    open_prices, close_prices, volume = _synthetic_panels()
    dup_index = pd.Index(list(_dates(3)) + [_dates(3)[-1]])
    dup_panel = pd.DataFrame({t: [1.0, 2.0, 3.0, 4.0] for t in TICKERS}, index=dup_index)
    with pytest.raises(ValueError, match="duplicate index"):
        compute_alpha2_components(dup_panel, dup_panel, dup_panel)

    rev_index = _dates(4)[::-1]
    rev_panel = pd.DataFrame({t: [1.0, 2.0, 3.0, 4.0] for t in TICKERS}, index=rev_index)
    with pytest.raises(ValueError, match="chronologically increasing"):
        compute_alpha2_components(rev_panel, rev_panel, rev_panel)


def test_no_future_leakage_for_all_components():
    open_prices, close_prices, volume = _synthetic_panels()
    cutoff = _dates()[5]

    before = compute_alpha2_components(open_prices, close_prices, volume)
    changed_open = open_prices.copy()
    changed_close = close_prices.copy()
    changed_volume = volume.copy()
    mask = changed_open.index > cutoff
    changed_open.loc[mask, :] *= 1.5
    changed_close.loc[mask, :] *= 0.5
    changed_volume.loc[mask, :] *= 10.0

    after = compute_alpha2_components(changed_open, changed_close, changed_volume)

    for name in before:
        assert before[name].loc[:cutoff].equals(after[name].loc[:cutoff]), name
