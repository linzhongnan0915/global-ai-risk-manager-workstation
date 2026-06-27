from __future__ import annotations

import pytest

from src.universe.models import SecurityMasterRecord
from src.universe.universe_definitions import UniverseDefinition
from src.universe.universe_filters import evaluate_security


AS_OF = "2026-06-22"


def _definition(**overrides) -> UniverseDefinition:
    data = {
        "name": "TEST",
        "description": "Test universe",
        "benchmark_family": "TEST",
        "intended_use": "Unit tests",
        "min_price": 5.0,
        "min_adv_20d": 1_000_000.0,
        "min_adv_60d": 750_000.0,
        "include_asset_types": ("COMMON_STOCK", "REIT_COMMON_EQUITY"),
        "exclude_asset_types": ("ETF", "ADR", "PREFERRED", "WARRANT", "UNIT", "CLOSED_END_FUND", "SPAC_SHELL"),
        "refresh_frequency": "daily",
        "min_market_cap": None,
        "max_market_cap": None,
    }
    data.update(overrides)
    return UniverseDefinition(**data)


def _record(**overrides) -> SecurityMasterRecord:
    data = {
        "security_id": "AAA",
        "ticker": "AAA",
        "company_name": "AAA Inc.",
        "asset_type": "COMMON_STOCK",
        "price": 20.0,
        "adv_20d": 2_000_000.0,
        "adv_60d": 1_500_000.0,
        "market_cap": 2_000_000_000.0,
        "last_updated": AS_OF,
        "data_source": "test",
    }
    data.update(overrides)
    return SecurityMasterRecord(**data)


@pytest.mark.parametrize(
    ("flag", "asset_type", "reason"),
    [
        ("is_etf", "ETF", "excluded_asset_type:ETF"),
        ("is_adr", "ADR", "excluded_asset_type:ADR"),
        ("is_preferred", "PREFERRED", "excluded_asset_type:PREFERRED"),
        ("is_warrant", "WARRANT", "excluded_asset_type:WARRANT"),
        ("is_unit", "UNIT", "excluded_asset_type:UNIT"),
        ("is_closed_end_fund", "CLOSED_END_FUND", "excluded_asset_type:CLOSED_END_FUND"),
        ("is_spac_shell", "SPAC_SHELL", "excluded_asset_type:SPAC_SHELL"),
    ],
)
def test_excludes_blocked_asset_types(flag, asset_type, reason):
    record = _record(asset_type=asset_type, **{flag: True})
    decision = evaluate_security(record, _definition(), as_of_date=AS_OF, stale_data_threshold_days=5)
    assert decision.included is False
    assert decision.reason == reason


def test_includes_common_stock_and_reit_common_equity():
    common = evaluate_security(_record(), _definition(), as_of_date=AS_OF, stale_data_threshold_days=5)
    reit = evaluate_security(
        _record(security_id="REIT", ticker="REIT", asset_type="REIT_COMMON_EQUITY", is_reit=True),
        _definition(),
        as_of_date=AS_OF,
        stale_data_threshold_days=5,
    )
    assert common.included is True
    assert reit.included is True


def test_applies_min_price_and_adv_filters():
    assert evaluate_security(_record(price=4.99), _definition(), as_of_date=AS_OF).reason == "min_price"
    assert evaluate_security(_record(adv_20d=999_999), _definition(), as_of_date=AS_OF).reason == "min_adv_20d"
    assert evaluate_security(_record(adv_60d=749_999), _definition(), as_of_date=AS_OF).reason == "min_adv_60d"


def test_applies_market_cap_filters_and_missing_required_values():
    small_cap_def = _definition(max_market_cap=10_000_000_000.0)
    assert evaluate_security(_record(market_cap=10_000_000_001.0), small_cap_def, as_of_date=AS_OF).reason == "max_market_cap"
    assert evaluate_security(_record(market_cap=None), small_cap_def, as_of_date=AS_OF).reason == "missing_market_cap"
    assert evaluate_security(_record(price=None), _definition(), as_of_date=AS_OF).reason == "missing_price"
    assert evaluate_security(_record(adv_20d=None), _definition(), as_of_date=AS_OF).reason == "missing_adv_20d"
    assert evaluate_security(_record(adv_60d=None), _definition(), as_of_date=AS_OF).reason == "missing_adv_60d"
