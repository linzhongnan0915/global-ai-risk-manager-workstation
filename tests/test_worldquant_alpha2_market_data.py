"""Unit tests for WorldQuant Alpha #2 market data download utilities."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.worldquant.market_data import (
    TICKER_STATUS_ALL_NAN,
    TICKER_STATUS_EMPTY,
    TICKER_STATUS_INSUFFICIENT_HISTORY,
    TICKER_STATUS_MISSING_COLUMNS,
    TICKER_STATUS_SUCCESS,
    assess_ticker_data_quality,
    build_symbol_map,
    classify_ticker_ohlcv,
    download_ohlcv,
    is_usable_ticker_status,
    map_ticker_to_provider,
    normalize_yfinance_history,
    validate_ohlcv_long_format,
)


def test_ordinary_ticker_mapping_unchanged():
    mapping = map_ticker_to_provider("aapl")
    assert mapping.ticker == "AAPL"
    assert mapping.provider_symbol == "AAPL"
    assert mapping.mapping_changed is False
    assert mapping.mapping_status == "unchanged"


def test_brk_dot_style_mapping():
    mapping = map_ticker_to_provider("brk.b")
    assert mapping.ticker == "BRK.B"
    assert mapping.provider_symbol == "BRK-B"
    assert mapping.mapping_changed is True
    assert mapping.mapping_status == "dot_to_dash"


def test_dash_symbol_mapping_unchanged():
    mapping = map_ticker_to_provider("BRK-B")
    assert mapping.provider_symbol == "BRK-B"
    assert mapping.mapping_status == "unchanged"


def test_unsupported_mapping_status():
    mapping = map_ticker_to_provider("FOO/BAR")
    assert mapping.mapping_status == "unsupported"
    assert mapping.provider_symbol == ""


def test_normalize_flat_column_response():
    raw = pd.DataFrame(
        {
            "Open": [10.0],
            "High": [11.0],
            "Low": [9.5],
            "Close": [10.5],
            "Adj Close": [10.4],
            "Volume": [1000.0],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )
    normalized = normalize_yfinance_history(raw, ticker="AAPL", provider_symbol="AAPL")
    assert normalized.loc[0, "ticker"] == "AAPL"
    assert normalized.loc[0, "close"] == pytest.approx(10.5)
    assert normalized.loc[0, "volume"] == pytest.approx(1000.0)


def test_normalize_multiindex_response():
    idx = pd.to_datetime(["2024-01-02"])
    raw = pd.DataFrame(
        {
            ("AAPL", "Open"): [10.0],
            ("AAPL", "High"): [11.0],
            ("AAPL", "Low"): [9.5],
            ("AAPL", "Close"): [10.5],
            ("AAPL", "Adj Close"): [10.4],
            ("AAPL", "Volume"): [1000.0],
        },
        index=idx,
    )
    raw.columns = pd.MultiIndex.from_tuples(raw.columns)
    normalized = normalize_yfinance_history(raw, ticker="AAPL", provider_symbol="AAPL")
    assert len(normalized) == 1
    assert normalized.loc[0, "adj_close"] == pytest.approx(10.4)


def test_download_one_success_one_failure():
    def fake_download(provider_symbols, *, start, end):
        assert provider_symbols == ["AAPL", "MSFT"]
        idx = pd.to_datetime(
            ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"]
        )
        return pd.DataFrame(
            {
                ("AAPL", "Open"): [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7],
                ("AAPL", "High"): [11.0, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7],
                ("AAPL", "Low"): [9.5, 9.6, 9.7, 9.8, 9.9, 10.0, 10.1, 10.2],
                ("AAPL", "Close"): [10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1, 11.2],
                ("AAPL", "Adj Close"): [10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1],
                ("AAPL", "Volume"): [1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0, 1600.0, 1700.0],
            },
            index=idx,
        ).pipe(lambda frame: frame.set_axis(pd.MultiIndex.from_tuples(frame.columns), axis=1))

    ohlcv, failures, symbol_map = download_ohlcv(
        ["AAPL", "MSFT"],
        start_date="2024-01-01",
        end_date="2024-01-15",
        batch_size=2,
        max_attempts=1,
        backoff_seconds=(0,),
        download_fn=fake_download,
    )
    assert set(ohlcv["ticker"]) == {"AAPL"}
    assert set(failures["ticker"]) == {"MSFT"}
    assert failures.iloc[0]["status"] == "empty"
    assert len(symbol_map) == 2


def test_download_retry_behavior():
    attempts = {"count": 0}

    def flaky_download(provider_symbols, *, start, end):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("temporary outage")
        idx = pd.to_datetime(
            ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"]
        )
        return pd.DataFrame(
            {
                ("AAPL", "Open"): [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7],
                ("AAPL", "High"): [11.0, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7],
                ("AAPL", "Low"): [9.5, 9.6, 9.7, 9.8, 9.9, 10.0, 10.1, 10.2],
                ("AAPL", "Close"): [10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1, 11.2],
                ("AAPL", "Adj Close"): [10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1],
                ("AAPL", "Volume"): [1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0, 1600.0, 1700.0],
            },
            index=idx,
        ).pipe(lambda frame: frame.set_axis(pd.MultiIndex.from_tuples(frame.columns), axis=1))

    ohlcv, failures, _ = download_ohlcv(
        ["AAPL"],
        start_date="2024-01-01",
        end_date="2024-01-15",
        batch_size=1,
        max_attempts=3,
        backoff_seconds=(0, 0, 0),
        download_fn=flaky_download,
    )
    assert attempts["count"] == 3
    assert len(ohlcv) == 8
    assert failures.empty


def test_download_partial_batch_success_on_batch_exception():
    calls: list[list[str]] = []

    def fake_download(provider_symbols, *, start, end):
        calls.append(list(provider_symbols))
        if provider_symbols == ["AAPL"]:
            idx = pd.to_datetime(
                ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"]
            )
            return pd.DataFrame(
                {
                    ("AAPL", "Open"): [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7],
                    ("AAPL", "High"): [11.0, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7],
                    ("AAPL", "Low"): [9.5, 9.6, 9.7, 9.8, 9.9, 10.0, 10.1, 10.2],
                    ("AAPL", "Close"): [10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1, 11.2],
                    ("AAPL", "Adj Close"): [10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1],
                    ("AAPL", "Volume"): [1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0, 1600.0, 1700.0],
                },
                index=idx,
            ).pipe(lambda frame: frame.set_axis(pd.MultiIndex.from_tuples(frame.columns), axis=1))
        raise ConnectionError("batch failed")

    ohlcv, failures, _ = download_ohlcv(
        ["AAPL", "MSFT"],
        start_date="2024-01-01",
        end_date="2024-01-10",
        batch_size=1,
        max_attempts=1,
        backoff_seconds=(0,),
        download_fn=fake_download,
    )
    assert calls == [["AAPL"], ["MSFT"]]
    assert set(ohlcv["ticker"]) == {"AAPL"}
    assert set(failures["ticker"]) == {"MSFT"}


def test_deterministic_batching_order():
    order: list[str] = []

    def fake_download(provider_symbols, *, start, end):
        order.extend(provider_symbols)
        return pd.DataFrame()

    download_ohlcv(
        ["MSFT", "AAPL", "BRK.B"],
        start_date="2024-01-01",
        end_date="2024-01-10",
        batch_size=2,
        max_attempts=1,
        backoff_seconds=(0,),
        download_fn=fake_download,
    )
    assert order == ["AAPL", "BRK-B", "MSFT"]


def test_validate_normalized_schema_and_duplicate_rejection():
    frame = pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "ticker": "AAPL",
                "provider_symbol": "AAPL",
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "adj_close": 1.4,
                "volume": 100.0,
                "source": "yfinance",
            },
            {
                "date": "2024-01-02",
                "ticker": "AAPL",
                "provider_symbol": "AAPL",
                "open": float("inf"),
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "adj_close": 1.4,
                "volume": 0.0,
                "source": "yfinance",
            },
        ]
    )
    with pytest.raises(ValueError, match="duplicate ticker-date"):
        validate_ohlcv_long_format(frame)

    clean = validate_ohlcv_long_format(frame.iloc[[0]].copy())
    clean.loc[0, "open"] = float("inf")
    validated = validate_ohlcv_long_format(clean)
    assert pd.isna(validated.loc[0, "open"])
    assert validated.loc[0, "volume"] == pytest.approx(100.0)

    zero_volume = clean.copy()
    zero_volume.loc[0, "volume"] = 0.0
    validated_zero = validate_ohlcv_long_format(zero_volume)
    assert validated_zero.loc[0, "volume"] == pytest.approx(0.0)


def test_build_symbol_map_is_deterministic():
    first = build_symbol_map(["MSFT", "AAPL", "BRK.B"])
    second = build_symbol_map(["BRK.B", "AAPL", "MSFT"])
    pd.testing.assert_frame_equal(first, second)


def _sample_row(ticker: str, day: str, *, close: float = 10.0, volume: float = 100.0) -> dict:
    return {
        "date": day,
        "ticker": ticker,
        "provider_symbol": ticker,
        "open": close - 0.5,
        "high": close + 0.5,
        "low": close - 1.0,
        "close": close,
        "adj_close": close,
        "volume": volume,
        "source": "test",
    }


def test_valid_market_data_passes_validation():
    frame = pd.DataFrame([_sample_row("AAPL", f"2024-01-{day:02d}", close=10 + day, volume=100 + day) for day in range(2, 12)])
    result = classify_ticker_ohlcv(frame, ticker="AAPL")
    assert result.status == TICKER_STATUS_SUCCESS
    assert result.usable_observation_count >= 8
    assert is_usable_ticker_status(result.status)


def test_empty_data_fails_validation():
    result = classify_ticker_ohlcv(pd.DataFrame(), ticker="AAPL")
    assert result.status == TICKER_STATUS_EMPTY
    assert not is_usable_ticker_status(result.status)


def test_all_nan_ohlcv_fails_validation():
    frame = pd.DataFrame(
        [
            {
                "date": f"2024-01-{day:02d}",
                "ticker": "AHR",
                "provider_symbol": "AHR",
                "open": float("nan"),
                "high": float("nan"),
                "low": float("nan"),
                "close": float("nan"),
                "adj_close": float("nan"),
                "volume": float("nan"),
                "source": "test",
            }
            for day in range(2, 27)
        ]
    )
    result = classify_ticker_ohlcv(frame, ticker="AHR")
    assert result.status == TICKER_STATUS_ALL_NAN
    assert result.usable_observation_count == 0
    assert not is_usable_ticker_status(result.status)


def test_missing_required_columns_fails_validation():
    frame = pd.DataFrame([{"date": "2024-01-02", "ticker": "AAPL", "close": 10.0}])
    result = classify_ticker_ohlcv(frame, ticker="AAPL")
    assert result.status == TICKER_STATUS_MISSING_COLUMNS
    assert not is_usable_ticker_status(result.status)


def test_insufficient_valid_history_is_identified():
    frame = pd.DataFrame([_sample_row("AAPL", f"2024-01-0{day}") for day in range(2, 7)])
    result = classify_ticker_ohlcv(frame, ticker="AAPL", min_valid_observations=8)
    assert result.status == TICKER_STATUS_INSUFFICIENT_HISTORY
    assert not is_usable_ticker_status(result.status)


def test_one_invalid_ticker_does_not_mark_whole_batch_success():
    def fake_download(provider_symbols, *, start, end):
        idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"])
        if provider_symbols == ["AAPL"]:
            return pd.DataFrame(
                {
                    ("AAPL", "Open"): [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7],
                    ("AAPL", "High"): [11.0, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7],
                    ("AAPL", "Low"): [9.5, 9.6, 9.7, 9.8, 9.9, 10.0, 10.1, 10.2],
                    ("AAPL", "Close"): [10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1, 11.2],
                    ("AAPL", "Adj Close"): [10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1],
                    ("AAPL", "Volume"): [1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0, 1600.0, 1700.0],
                },
                index=idx,
            ).pipe(lambda frame: frame.set_axis(pd.MultiIndex.from_tuples(frame.columns), axis=1))
        return pd.DataFrame(
            {
                ("AHR", "Open"): [float("nan")] * 8,
                ("AHR", "High"): [float("nan")] * 8,
                ("AHR", "Low"): [float("nan")] * 8,
                ("AHR", "Close"): [float("nan")] * 8,
                ("AHR", "Adj Close"): [float("nan")] * 8,
                ("AHR", "Volume"): [float("nan")] * 8,
            },
            index=idx,
        ).pipe(lambda frame: frame.set_axis(pd.MultiIndex.from_tuples(frame.columns), axis=1))

    ohlcv, failures, _ = download_ohlcv(
        ["AAPL", "AHR"],
        start_date="2024-01-01",
        end_date="2024-01-15",
        batch_size=1,
        max_attempts=1,
        backoff_seconds=(0,),
        download_fn=fake_download,
    )
    quality = assess_ticker_data_quality(ohlcv, ["AAPL", "AHR"])
    failures_lookup = failures.set_index("ticker")
    assert set(ohlcv["ticker"]) == {"AAPL"}
    assert set(failures["ticker"]) == {"AHR"}
    assert failures.iloc[0]["status"] == TICKER_STATUS_ALL_NAN
    assert quality.loc[quality["ticker"] == "AAPL", "status"].iloc[0] == TICKER_STATUS_SUCCESS
    assert failures_lookup.loc["AHR", "status"] == TICKER_STATUS_ALL_NAN


def test_merge_preserves_download_quality_metrics_for_rejected_partial_data():
    failures = pd.DataFrame(
        [
            {
                "ticker": "AHR",
                "provider_symbol": "AHR",
                "batch_id": 0,
                "attempts": 1,
                "error_type": "ValueError",
                "error_message": "36 usable observations with 41.0% missing Alpha #2 critical values",
                "status": "partial_data",
                "row_count": 61,
                "usable_observation_count": 36,
                "missing_value_count": 100,
                "missing_value_ratio": 0.41,
            }
        ]
    )
    from src.strategies.worldquant.market_data import merge_download_failures_into_quality_report

    quality = assess_ticker_data_quality(pd.DataFrame(), ["AHR"])
    merged = merge_download_failures_into_quality_report(quality, failures)
    ahr = merged.loc[merged["ticker"] == "AHR"].iloc[0]

    assert ahr["status"] == "partial_data"
    assert ahr["row_count"] == 61
    assert ahr["usable_observation_count"] == 36
    assert ahr["missing_value_ratio"] == pytest.approx(0.41)
    assert ahr["reason"] == failures.iloc[0]["error_message"]
    assert pd.notna(ahr["batch_id"])
    assert pd.notna(ahr["attempts"])


def test_legacy_failure_merge_preserves_status_without_fabricating_metrics():
    failures = pd.DataFrame(
        [
            {
                "ticker": "AHR",
                "provider_symbol": "AHR",
                "batch_id": 0,
                "attempts": 1,
                "error_type": "ValueError",
                "error_message": "legacy cached failure reason",
                "status": "partial_data",
            }
        ]
    )
    from src.strategies.worldquant.market_data import merge_download_failures_into_quality_report

    quality = assess_ticker_data_quality(pd.DataFrame(), ["AHR"])
    merged = merge_download_failures_into_quality_report(quality, failures)
    ahr = merged.loc[merged["ticker"] == "AHR"].iloc[0]

    assert ahr["status"] == "partial_data"
    assert ahr["reason"] == "legacy cached failure reason"
    assert pd.isna(ahr["row_count"])
    assert pd.isna(ahr["usable_observation_count"])


def test_missing_high_low_only_does_not_reject_alpha2_ticker():
    rows = []
    for day in range(2, 12):
        rows.append(
            {
                "date": f"2024-01-{day:02d}",
                "ticker": "AAPL",
                "provider_symbol": "AAPL",
                "open": 10.0 + day,
                "high": float("nan"),
                "low": float("nan"),
                "close": 10.5 + day,
                "adj_close": 10.4 + day,
                "volume": 1000.0 + day,
                "source": "test",
            }
        )
    frame = pd.DataFrame(rows)
    result = classify_ticker_ohlcv(frame, ticker="AAPL")
    assert result.status == TICKER_STATUS_SUCCESS


def test_missing_critical_volume_marks_partial_data():
    rows = []
    for day in range(2, 12):
        row = _sample_row("AAPL", f"2024-01-{day:02d}", close=10 + day, volume=100 + day)
        if day in {10, 11}:
            row["volume"] = float("nan")
        rows.append(row)
    frame = pd.DataFrame(rows)
    result = classify_ticker_ohlcv(frame, ticker="AAPL")
    assert result.status == "partial_data"
    assert result.usable_observation_count >= 8
    assert not is_usable_ticker_status(result.status)
