from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.universe.universe_builder import UniverseBuilder
from src.universe.yfinance_provider import (
    DATA_SOURCE,
    POINT_IN_TIME_STATUS,
    RESEARCH_USE,
    YFinanceProvisionalUniverseProvider,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeTicker:
    def __init__(self, symbol: str, fundamentals: dict[str, dict]):
        self.symbol = symbol
        self._fundamentals = fundamentals.get(symbol, {})

    @property
    def fast_info(self):
        return {"market_cap": self._fundamentals.get("market_cap")}

    @property
    def info(self):
        return {
            "marketCap": self._fundamentals.get("market_cap"),
            "sector": self._fundamentals.get("sector"),
            "industry": self._fundamentals.get("industry"),
            "quoteType": self._fundamentals.get("quote_type", "EQUITY"),
        }


class FakeYFinance:
    def __init__(self, frame: pd.DataFrame, fundamentals: dict[str, dict] | None = None, *, fail_symbols=None):
        self.frame = frame
        self.fundamentals = fundamentals or {}
        self.fail_symbols = set(fail_symbols or [])

    def download(self, *, tickers, **kwargs):
        requested = [tickers] if isinstance(tickers, str) else list(tickers)
        if self.fail_symbols.intersection(requested):
            raise RuntimeError("mock yfinance chunk failure")
        columns = [column for column in self.frame.columns if column[0] in requested]
        return self.frame.loc[:, columns].copy() if columns else pd.DataFrame()

    def Ticker(self, symbol: str):
        return FakeTicker(symbol, self.fundamentals)


def _write_reference_inputs(root: Path, *, tickers=("AAA", "BBB", "CCC")) -> None:
    sp500_path = root / "dashboard" / "data" / "universes" / "sp500_current.json"
    sp500_path.parent.mkdir(parents=True, exist_ok=True)
    sp500_path.write_text(
        json.dumps(
            {
                "as_of_date": "2026-06-22",
                "constituents": [
                    {
                        "ticker": "AAA",
                        "company_name": "Alpha Inc.",
                        "sector": "Information Technology",
                        "industry": "Software",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    reference_path = root / "data" / "reference" / "worldquant_alpha2_research_universe_v1.csv"
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "symbol_raw": ticker,
                "symbol_normalized": ticker,
                "security_name": f"{ticker} Corp. - Common Stock",
                "listing_exchange": "NASDAQ",
                "classification": "common_stock",
                "is_adr": False,
                "is_reit": False,
                "eligible_candidate": True,
                "duplicate_symbol": False,
            }
            for ticker in tickers
        ]
    ).to_csv(reference_path, index=False)


def _price_frame(
    tickers: list[str],
    *,
    days: int = 65,
    missing_price: set[str] | None = None,
    missing_volume: set[str] | None = None,
) -> pd.DataFrame:
    missing_price = missing_price or set()
    missing_volume = missing_volume or set()
    index = pd.date_range("2026-03-23", periods=days, freq="B")
    columns = pd.MultiIndex.from_product([tickers, ["Close", "Volume"]])
    frame = pd.DataFrame(index=index, columns=columns, dtype="float64")
    for ticker_idx, ticker in enumerate(tickers):
        if ticker not in missing_price:
            frame[(ticker, "Close")] = 10.0 + ticker_idx + pd.Series(range(days), index=index) * 0.1
        if ticker not in missing_volume:
            frame[(ticker, "Volume")] = 1_000_000 + ticker_idx * 100_000
    return frame


def _provider(root: Path, fake_yfinance: FakeYFinance, **kwargs) -> YFinanceProvisionalUniverseProvider:
    return YFinanceProvisionalUniverseProvider(
        root,
        definitions_path=ROOT / "data" / "config" / "universe_definitions.yaml",
        yfinance_module=fake_yfinance,
        allow_symbol_directory_download=False,
        force_refresh=True,
        use_cache=False,
        **kwargs,
    )


def test_yfinance_provider_maps_price_volume_to_latest_price_and_adv(tmp_path: Path):
    _write_reference_inputs(tmp_path, tickers=("AAA",))
    fake = FakeYFinance(
        _price_frame(["AAA"]),
        {"AAA": {"market_cap": 120_000_000_000, "sector": "Technology", "industry": "Software"}},
    )
    response = _provider(tmp_path, fake, universe_names=["US_LARGE_CAP_CORE"]).fetch_security_master_candidates(
        as_of_date="2026-06-22"
    )

    record = response.records[0]
    expected_dollar_volume = record.price * 1_000_000
    assert response.source == DATA_SOURCE
    assert record.price == pytest.approx(16.4)
    assert record.adv_20d == pytest.approx(expected_dollar_volume - 0.95 * 1_000_000)
    assert record.adv_60d is not None
    assert record.market_cap == 120_000_000_000
    assert record.sector == "Technology"


def test_missing_price_and_adv_drive_exclusion_without_fabrication(tmp_path: Path):
    _write_reference_inputs(tmp_path, tickers=("AAA", "BBB", "CCC"))
    fake = FakeYFinance(
        _price_frame(["AAA", "BBB", "CCC"], missing_price={"BBB"}, missing_volume={"CCC"}),
        {
            "AAA": {"market_cap": 10_000_000_000, "sector": "Technology", "industry": "Software"},
            "BBB": {"market_cap": 10_000_000_000, "sector": "Industrials", "industry": "Machinery"},
            "CCC": {"market_cap": 10_000_000_000, "sector": "Health Care", "industry": "Biotech"},
        },
    )
    provider = _provider(tmp_path, fake, universe_names=["US_BROAD_MARKET"])
    result = UniverseBuilder(
        root=ROOT,
        output_dir=tmp_path / "data" / "universe",
        provider=provider,
        universe_names=["US_BROAD_MARKET"],
    ).build(as_of_date="2026-06-22")

    broad = result.snapshot_payload["universes"]["US_BROAD_MARKET"]
    assert broad["included_count"] == 1
    assert broad["excluded_by_reason"]["missing_price"] == 1
    assert broad["excluded_by_reason"]["missing_adv_20d"] == 1
    assert result.snapshot_payload["data_source"] == DATA_SOURCE
    assert result.snapshot_payload["research_use"] == RESEARCH_USE
    assert result.snapshot_payload["not_survivor_bias_free"] is True


def test_missing_market_cap_is_surfaced_as_warning(tmp_path: Path):
    _write_reference_inputs(tmp_path, tickers=("AAA",))
    fake = FakeYFinance(_price_frame(["AAA"]), {"AAA": {"sector": "Technology", "industry": "Software"}})
    response = _provider(tmp_path, fake, universe_names=["US_BROAD_MARKET"]).fetch_security_master_candidates(
        as_of_date="2026-06-22"
    )

    assert response.records[0].market_cap is None
    assert response.metadata["field_warning_counts"]["missing_market_cap"] == 1
    assert any("missing_market_cap" in warning for warning in response.warnings)


def test_partial_yfinance_failures_do_not_crash_refresh(tmp_path: Path):
    _write_reference_inputs(tmp_path, tickers=("AAA", "FAIL"))
    fake = FakeYFinance(
        _price_frame(["AAA", "FAIL"]),
        {"AAA": {"market_cap": 10_000_000_000}, "FAIL": {"market_cap": 1_000_000_000}},
        fail_symbols={"FAIL"},
    )
    response = _provider(
        tmp_path,
        fake,
        universe_names=["US_BROAD_MARKET"],
        chunk_size=1,
    ).fetch_security_master_candidates(as_of_date="2026-06-22")

    by_ticker = {record.ticker: record for record in response.records}
    assert by_ticker["AAA"].price is not None
    assert by_ticker["FAIL"].price is None
    assert response.status == "PARTIAL_YFINANCE_PUBLIC_FALLBACK_PROVISIONAL"
    assert response.metadata["ticker_failures"] == ["FAIL"]


def test_provisional_labels_are_written_to_diagnostics(tmp_path: Path):
    _write_reference_inputs(tmp_path, tickers=("AAA",))
    fake = FakeYFinance(_price_frame(["AAA"]), {"AAA": {"market_cap": 10_000_000_000}})
    response = _provider(tmp_path, fake, universe_names=["US_BROAD_MARKET"]).fetch_security_master_candidates(
        as_of_date="2026-06-22"
    )
    diagnostics = json.loads((tmp_path / "data/universe/yfinance_provisional_diagnostics.json").read_text())

    assert response.source == DATA_SOURCE
    assert diagnostics["data_source"] == DATA_SOURCE
    assert diagnostics["point_in_time_status"] == POINT_IN_TIME_STATUS
    assert diagnostics["research_use"] == RESEARCH_USE
    assert diagnostics["not_survivor_bias_free"] is True
