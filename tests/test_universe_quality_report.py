from __future__ import annotations

from src.universe.models import UniverseSnapshot
from src.universe.quality_report import build_quality_report, summarize_snapshot_for_api


def test_quality_report_summarizes_counts_exclusions_and_warnings():
    snapshot = UniverseSnapshot(
        universe_name="US_TEST",
        as_of_date="2026-06-22",
        version="v1",
        total_candidates=3,
        included_count=1,
        excluded_count=2,
        included_tickers=["AAA"],
        excluded_by_reason={"missing_price": 1, "excluded_asset_type:ETF": 1},
        sector_counts={"Technology": 1},
        data_quality_warnings=["Current membership only provisional."],
        data_source="test",
        point_in_time_status="CURRENT_MEMBERSHIP_ONLY_PROVISIONAL",
        last_refresh_time="2026-06-22T12:00:00+00:00",
    )
    report = build_quality_report(
        {"US_TEST": snapshot},
        provider_status={"status": "LOADED_TEST"},
        parquet_status={"fallback": "CSV_JSON_ONLY"},
    )
    assert report["total_included_by_universe"]["US_TEST"] == 1
    assert report["excluded_by_reason_total"]["missing_price"] == 1
    assert report["parquet_status"]["fallback"] == "CSV_JSON_ONLY"
    assert report["provisional_data_warnings"]


def test_snapshot_api_summary_contract_includes_required_fields():
    snapshot = UniverseSnapshot(
        universe_name="US_TEST",
        as_of_date="2026-06-22",
        version="v1",
        total_candidates=1,
        included_count=1,
        excluded_count=0,
        data_source="test",
        point_in_time_status="CURRENT_MEMBERSHIP_ONLY_PROVISIONAL",
        last_refresh_time="2026-06-22T12:00:00+00:00",
    )
    payload = summarize_snapshot_for_api(snapshot)
    assert payload["universe_name"] == "US_TEST"
    assert payload["included_count"] == 1
    assert payload["excluded_by_reason"] == {}
    assert payload["point_in_time_status"] == "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"
