from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.universe.file_provider import FileUniverseProvider
from src.universe.universe_builder import UniverseBuilder


def write_valid_provider_inputs(input_dir: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "security_id": "SEC-A",
                "ticker": " aaa ",
                "company_name": "Alpha Provider Corp",
                "exchange": "NYSE",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "currency": "USD",
                "is_active": "true",
                "data_source": "boss_security_master_file",
                "last_updated": "2026-06-22",
            },
            {
                "security_id": "SEC-B",
                "ticker": "BBB",
                "company_name": "Beta Provider Corp",
                "exchange": "NASDAQ",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "currency": "USD",
                "is_active": "true",
                "data_source": "boss_security_master_file",
                "last_updated": "2026-06-22",
            },
            {
                "security_id": "SEC-C",
                "ticker": "CCC",
                "company_name": "Missing Price Corp",
                "exchange": "NYSE",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "currency": "USD",
                "is_active": "true",
                "data_source": "boss_security_master_file",
                "last_updated": "2026-06-22",
            },
            {
                "security_id": "SEC-D",
                "ticker": "ETFZ",
                "company_name": "ETF Provider Fund",
                "exchange": "NYSE",
                "asset_type": "ETF",
                "country": "US",
                "currency": "USD",
                "is_active": "true",
                "is_etf": "true",
                "data_source": "boss_security_master_file",
                "last_updated": "2026-06-22",
            },
        ]
    ).to_csv(input_dir / "security_master.csv", index=False)
    pd.DataFrame(
        [
            {
                "security_id": "SEC-A",
                "ticker": "AAA",
                "as_of_date": "2026-06-22",
                "price": "110.50",
                "adv_20d": "25000000",
                "adv_60d": "21000000",
                "market_cap": "120000000000",
                "currency": "USD",
                "data_source": "boss_price_volume_file",
                "last_updated": "2026-06-22",
            },
            {
                "security_id": "SEC-B",
                "ticker": "BBB",
                "as_of_date": "2026-06-22",
                "price": "12.75",
                "adv_20d": "6000000",
                "adv_60d": "4500000",
                "market_cap": "5000000000",
                "currency": "USD",
                "data_source": "boss_price_volume_file",
                "last_updated": "2026-06-22",
            },
            {
                "security_id": "SEC-D",
                "ticker": "ETFZ",
                "as_of_date": "2026-06-22",
                "price": "50.00",
                "adv_20d": "50000000",
                "adv_60d": "45000000",
                "market_cap": "50000000000",
                "currency": "USD",
                "data_source": "boss_price_volume_file",
                "last_updated": "2026-06-22",
            },
        ]
    ).to_csv(input_dir / "prices_volume_snapshot.csv", index=False)
    pd.DataFrame(
        [
            {
                "security_id": "SEC-A",
                "ticker": "AAA",
                "sector": "Information Technology",
                "industry": "Software",
                "data_source": "boss_sector_file",
                "last_updated": "2026-06-22",
            },
            {
                "security_id": "SEC-B",
                "ticker": "BBB",
                "sector": "Industrials",
                "industry": "Electrical Equipment",
                "data_source": "boss_sector_file",
                "last_updated": "2026-06-22",
            },
            {
                "security_id": "SEC-C",
                "ticker": "CCC",
                "sector": "Health Care",
                "industry": "Biotechnology",
                "data_source": "boss_sector_file",
                "last_updated": "2026-06-22",
            },
            {
                "security_id": "SEC-D",
                "ticker": "ETFZ",
                "sector": "Financials",
                "industry": "Exchange Traded Fund",
                "data_source": "boss_sector_file",
                "last_updated": "2026-06-22",
            },
        ]
    ).to_csv(input_dir / "sector_industry.csv", index=False)
    pd.DataFrame(
        [
            {
                "security_id": security_id,
                "ticker": ticker,
                "index_name": "BOSS_APPROVED_CURRENT_UNIVERSE",
                "membership_start_date": "2026-01-01",
                "membership_end_date": "",
                "as_of_date": "2026-06-22",
                "data_source": "boss_index_membership_file",
                "last_updated": "2026-06-22",
            }
            for security_id, ticker in (("SEC-A", "AAA"), ("SEC-B", "BBB"), ("SEC-C", "CCC"), ("SEC-D", "ETFZ"))
        ]
    ).to_csv(input_dir / "index_membership.csv", index=False)


def test_valid_provider_csv_loads_and_preserves_security_id(tmp_path: Path):
    input_dir = tmp_path / "provider_inputs"
    write_valid_provider_inputs(input_dir)

    response = FileUniverseProvider(input_dir).fetch_security_master_candidates(as_of_date="2026-06-22")
    by_ticker = {record.ticker: record for record in response.records}

    assert response.status == "LOADED_FILE_PROVIDER"
    assert set(by_ticker) == {"AAA", "BBB", "CCC", "ETFZ"}
    assert by_ticker["AAA"].security_id == "SEC-A"
    assert by_ticker["AAA"].price == 110.50
    assert by_ticker["AAA"].adv_20d == 25_000_000
    assert by_ticker["AAA"].sector == "Information Technology"
    assert "price=boss_price_volume_file" in by_ticker["AAA"].data_source


def test_missing_price_adv_causes_exclusion_not_fake_inclusion(tmp_path: Path):
    input_dir = tmp_path / "provider_inputs"
    write_valid_provider_inputs(input_dir)
    builder = UniverseBuilder(
        root=Path("."),
        output_dir=tmp_path / "data/universe",
        provider=FileUniverseProvider(input_dir),
    )

    result = builder.build(as_of_date="2026-06-22")
    large = result.snapshot_payload["universes"]["US_LARGE_CAP_CORE"]

    assert large["included_count"] == 1
    assert large["excluded_by_reason"]["missing_price"] == 1
    assert large["excluded_by_reason"]["excluded_asset_type:ETF"] == 1
    assert "AAA" in large["included_tickers"]


def test_templates_folder_is_not_used_as_production_input(tmp_path: Path):
    template_dir = tmp_path / "provider_inputs" / "templates"
    template_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "security_id": "SAMPLE-SEC-001",
                "ticker": "SAMP_A",
                "company_name": "Sample Template Alpha Corp",
                "exchange": "NYSE",
                "asset_type": "COMMON_STOCK",
                "country": "US",
                "currency": "USD",
                "is_active": "true",
                "data_source": "SAMPLE_TEMPLATE_ONLY",
                "last_updated": "2026-06-22",
            }
        ]
    ).to_csv(template_dir / "security_master.csv", index=False)

    response = FileUniverseProvider(tmp_path / "provider_inputs").fetch_security_master_candidates(as_of_date="2026-06-22")

    assert response.records == []
    assert response.status == "UNAVAILABLE"
    assert any("security_master.csv is unavailable" in warning for warning in response.warnings)
