"""End-to-end tests for WorldQuant Alpha #2 research backtest."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategies.worldquant.backtest import run_alpha2_backtest, write_alpha2_backtest_outputs
from src.strategies.worldquant.market_data import OHLCV_LONG_COLUMNS, TICKER_STATUS_ALL_NAN
from src.strategies.worldquant.portfolio import signal_to_dollar_neutral_weights


def _synthetic_ohlcv(tickers: list[str], days: int = 20) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2024-01-02", periods=days, freq="B")
    rng = np.random.default_rng(42)
    for ticker_idx, ticker in enumerate(tickers):
        open_base = 10.0 + ticker_idx * 3.0
        volume_base = 500.0 + ticker_idx * 137.0
        for day_idx, day in enumerate(dates):
            shock = float(rng.normal(0.0, 0.4 + ticker_idx * 0.05))
            close = open_base + day_idx * (0.03 + ticker_idx * 0.02) + shock
            open_px = close - 0.15 + ticker_idx * 0.01 + float(rng.normal(0.0, 0.05))
            volume = max(volume_base + day_idx * (25 + ticker_idx * 11) + float(rng.normal(0.0, 40.0)), 1.0)
            rows.append(
                {
                    "date": day.date().isoformat(),
                    "ticker": ticker,
                    "provider_symbol": ticker,
                    "open": open_px,
                    "high": close + 0.5,
                    "low": min(open_px, close) - 0.5,
                    "close": close,
                    "adj_close": close,
                    "volume": volume,
                    "source": "test",
                }
            )
    return pd.DataFrame(rows, columns=OHLCV_LONG_COLUMNS)


def test_signal_to_weights_is_dollar_neutral_with_long_and_short():
    index = pd.bdate_range("2024-01-02", periods=3, freq="B")
    signal = pd.DataFrame(
        {
            "AAA": [1.0, 1.1, 0.9],
            "BBB": [0.2, -0.1, 0.0],
            "CCC": [-0.5, -0.8, -1.0],
            "DDD": [0.0, 0.3, 0.2],
        },
        index=index,
    )
    weights = signal_to_dollar_neutral_weights(signal, long_quantile=0.5, short_quantile=0.5)
    for date in index:
        row = weights.loc[date]
        assert row.abs().sum() == pytest.approx(1.0)
        assert row.sum() == pytest.approx(0.0)
        assert (row > 0).any()
        assert (row < 0).any()


def test_end_to_end_backtest_smoke_universe(tmp_path):
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    ohlcv = _synthetic_ohlcv(tickers, days=24)
    result = run_alpha2_backtest(ohlcv, tickers)

    assert result.run_status == "completed"
    assert not result.signal.isna().all().all()
    assert result.weights.abs().sum().sum() > 0
    assert (result.weights > 0).any().any()
    assert (result.weights < 0).any().any()
    assert not np.isinf(result.daily_returns["net_return"]).any()

    compounded = float(np.prod(1.0 + result.daily_returns["net_return"].to_numpy()) - 1.0)
    assert result.summary.iloc[0]["cumulative_net_return"] == pytest.approx(compounded)
    assert result.summary.iloc[0]["execution_mode"] == "next_open_to_close"
    assert result.summary.iloc[0]["execution_lag"] == 1
    assert result.summary.iloc[0]["return_definition"] == "open_to_close"

    sample = result.signal_sample
    assert not sample.empty
    assert (sample["side"] == "long").any()
    assert (sample["side"] == "short").any()
    assert (sample["executed_position"] > 0).any()
    assert (sample["executed_position"] < 0).any()
    first = sample.iloc[0]
    assert first["signal_date"] != first["execution_date"]
    assert result.executed_weights.loc[pd.Timestamp(first["execution_date"]), first["ticker"]] == pytest.approx(
        first["executed_position"]
    )

    rejected = result.quality_report.loc[result.quality_report["status"] == TICKER_STATUS_ALL_NAN, "ticker"].tolist()
    assert rejected == []

    paths = write_alpha2_backtest_outputs(result, tmp_path)
    for path in paths.values():
        assert path.exists()


def test_rejected_ticker_excluded_from_signal_path():
    tickers = ["GOOD1", "GOOD2", "GOOD3", "BAD"]
    good = _synthetic_ohlcv(["GOOD1", "GOOD2", "GOOD3"], days=20)
    bad = pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "ticker": "BAD",
                "provider_symbol": "BAD",
                "open": float("nan"),
                "high": float("nan"),
                "low": float("nan"),
                "close": float("nan"),
                "adj_close": float("nan"),
                "volume": float("nan"),
                "source": "test",
            }
        ]
    )
    ohlcv = pd.concat([good, bad], ignore_index=True)
    result = run_alpha2_backtest(ohlcv, tickers)
    assert "BAD" not in result.signal.columns
    assert result.quality_report.loc[result.quality_report["ticker"] == "BAD", "status"].iloc[0] == TICKER_STATUS_ALL_NAN
