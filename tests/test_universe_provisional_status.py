from __future__ import annotations

from pathlib import Path

from src.universe.universe_builder import UniverseBuilder
from src.universe.universe_refresh_service import universe_members_payload, universe_summary_payload
from src.universe.yfinance_provider import DATA_SOURCE, POINT_IN_TIME_STATUS, RESEARCH_USE, YFinanceProvisionalUniverseProvider
from tests.test_yfinance_provisional_provider import FakeYFinance, _price_frame, _write_reference_inputs

ROOT = Path(__file__).resolve().parents[1]


def test_api_contract_exposes_yfinance_provisional_status(tmp_path: Path):
    _write_reference_inputs(tmp_path, tickers=("AAA",))
    fake = FakeYFinance(
        _price_frame(["AAA"]),
        {"AAA": {"market_cap": 100_000_000_000, "sector": "Technology", "industry": "Software"}},
    )
    provider = YFinanceProvisionalUniverseProvider(
        tmp_path,
        definitions_path=ROOT / "data" / "config" / "universe_definitions.yaml",
        yfinance_module=fake,
        allow_symbol_directory_download=False,
        force_refresh=True,
        use_cache=False,
        universe_names=["US_BROAD_MARKET"],
    )
    UniverseBuilder(
        root=ROOT,
        output_dir=tmp_path / "data" / "universe",
        provider=provider,
        universe_names=["US_BROAD_MARKET"],
    ).build(as_of_date="2026-06-22")

    summary = universe_summary_payload(tmp_path)
    members = universe_members_payload(tmp_path, universe_name="US_BROAD_MARKET")

    assert summary["data_source"] == DATA_SOURCE
    assert summary["point_in_time_status"] == POINT_IN_TIME_STATUS
    assert summary["research_use"] == RESEARCH_USE
    assert summary["not_survivor_bias_free"] is True
    assert summary["universes"]["US_BROAD_MARKET"]["data_source"] == DATA_SOURCE
    assert summary["universes"]["US_BROAD_MARKET"]["not_survivor_bias_free"] is True
    assert members["source"] == DATA_SOURCE
    assert members["point_in_time_status"] == POINT_IN_TIME_STATUS
    assert members["research_use"] == RESEARCH_USE
    assert members["not_survivor_bias_free"] is True


def test_dashboard_contract_keeps_provisional_warning_visible():
    source = (ROOT / "dashboard" / "foundation-app.js").read_text(encoding="utf-8")

    assert "DATA_SOURCE" in source
    assert "RESEARCH_USE" in source
    assert "PROTOTYPE_ONLY" in source
    assert "not survivor-bias-free" in source
    assert "not direct optimizer input" in source
