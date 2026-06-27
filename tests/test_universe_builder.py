from __future__ import annotations

import json
from pathlib import Path

from src.universe.models import SecurityMasterRecord
from src.universe.providers import ProviderResponse, UniverseDataProvider
from src.universe.universe_builder import UniverseBuilder


class InMemoryProvider(UniverseDataProvider):
    source_name = "test_provider"

    def __init__(self, records: list[SecurityMasterRecord]):
        self.records = records

    def fetch_security_master_candidates(self, *, as_of_date: str | None = None) -> ProviderResponse:
        return ProviderResponse(
            records=self.records,
            status="LOADED_TEST",
            source=self.source_name,
            warnings=["test provider"],
        )


def _record(ticker: str, **overrides) -> SecurityMasterRecord:
    data = {
        "security_id": ticker,
        "ticker": ticker,
        "company_name": f"{ticker} Inc.",
        "asset_type": "COMMON_STOCK",
        "sector": "Technology",
        "industry": "Software",
        "price": 20.0,
        "adv_20d": 25_000_000.0,
        "adv_60d": 20_000_000.0,
        "market_cap": 5_000_000_000.0,
        "last_updated": "2026-06-22",
        "data_source": "test",
    }
    data.update(overrides)
    return SecurityMasterRecord(**data)


def test_universe_builder_produces_versioned_snapshots_and_artifacts(tmp_path: Path):
    records = [
        _record("AAA"),
        _record("BBB", asset_type="ETF", is_etf=True),
        _record("CCC", price=None),
        _record("DDD", market_cap=12_000_000_000.0),
    ]
    output_dir = tmp_path / "data/universe"
    builder = UniverseBuilder(
        root=Path("."),
        output_dir=output_dir,
        provider=InMemoryProvider(records),
    )

    result = builder.build(as_of_date="2026-06-22")
    snapshot = result.snapshot_payload
    large = snapshot["universes"]["US_LARGE_CAP_CORE"]
    small = snapshot["universes"]["US_SMALL_CAP"]

    assert snapshot["version"] == "universe_foundation_v1_20260622"
    assert large["total_candidates"] == 4
    assert large["included_count"] == 2
    assert large["excluded_count"] == 2
    assert large["excluded_by_reason"]["excluded_asset_type:ETF"] == 1
    assert large["excluded_by_reason"]["missing_price"] == 1
    assert small["excluded_by_reason"]["max_market_cap"] == 1
    assert "AAA" in large["included_tickers"]
    assert "DDD" in large["included_tickers"]
    assert result.membership_rows > 0
    assert (output_dir / "security_master.csv").exists()
    assert (output_dir / "universe_membership.csv").exists()
    assert (output_dir / "current_universe_snapshot.json").exists()
    assert (output_dir / "universe_quality_report.json").exists()
    assert (output_dir / "universe_refresh_log.jsonl").exists()

    saved = json.loads((output_dir / "current_universe_snapshot.json").read_text(encoding="utf-8"))
    assert saved["universes"]["US_LARGE_CAP_CORE"]["point_in_time_status"] == "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"


def test_builder_records_exclusion_reasons_for_all_filtered_candidates(tmp_path: Path):
    records = [_record("AAA"), _record("LOW", adv_20d=1.0), _record("MISS", adv_60d=None)]
    builder = UniverseBuilder(root=Path("."), output_dir=tmp_path, provider=InMemoryProvider(records))
    result = builder.build(as_of_date="2026-06-22")
    exclusions = result.snapshot_payload["exclusions"]
    reasons = {(row["ticker"], row["exclusion_reason"]) for row in exclusions}
    assert ("LOW", "min_adv_20d") in reasons
    assert ("MISS", "missing_adv_60d") in reasons
