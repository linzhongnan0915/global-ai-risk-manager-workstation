"""Transparent universe inclusion and exclusion filters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.universe.models import SecurityMasterRecord
from src.universe.universe_definitions import UniverseDefinition


@dataclass(frozen=True)
class FilterDecision:
    included: bool
    reason: str


EXCLUSION_FLAG_BY_ASSET_TYPE = {
    "ETF": "is_etf",
    "ADR": "is_adr",
    "PREFERRED": "is_preferred",
    "WARRANT": "is_warrant",
    "UNIT": "is_unit",
    "CLOSED_END_FUND": "is_closed_end_fund",
    "SPAC_SHELL": "is_spac_shell",
}


def evaluate_security(
    record: SecurityMasterRecord,
    definition: UniverseDefinition,
    *,
    as_of_date: str | date | datetime,
    stale_data_threshold_days: int | None = None,
) -> FilterDecision:
    if not record.is_active:
        return FilterDecision(False, "inactive_security")

    asset_type = _canonical_asset_type(record)
    excluded_type = _excluded_asset_type(record, asset_type, definition.exclude_asset_types)
    if excluded_type:
        return FilterDecision(False, f"excluded_asset_type:{excluded_type}")
    if asset_type not in definition.include_asset_types:
        return FilterDecision(False, f"asset_type_not_included:{asset_type}")

    if record.price is None:
        return FilterDecision(False, "missing_price")
    if record.price < definition.min_price:
        return FilterDecision(False, "min_price")

    if record.adv_20d is None:
        return FilterDecision(False, "missing_adv_20d")
    if record.adv_20d < definition.min_adv_20d:
        return FilterDecision(False, "min_adv_20d")

    if record.adv_60d is None:
        return FilterDecision(False, "missing_adv_60d")
    if record.adv_60d < definition.min_adv_60d:
        return FilterDecision(False, "min_adv_60d")

    if definition.min_market_cap is not None or definition.max_market_cap is not None:
        if record.market_cap is None:
            return FilterDecision(False, "missing_market_cap")
        if definition.min_market_cap is not None and record.market_cap < definition.min_market_cap:
            return FilterDecision(False, "min_market_cap")
        if definition.max_market_cap is not None and record.market_cap > definition.max_market_cap:
            return FilterDecision(False, "max_market_cap")

    if stale_data_threshold_days is not None:
        stale_reason = _stale_reason(record, as_of_date, stale_data_threshold_days)
        if stale_reason:
            return FilterDecision(False, stale_reason)

    return FilterDecision(True, "included")


def apply_universe_filters(
    records: list[SecurityMasterRecord],
    definition: UniverseDefinition,
    *,
    as_of_date: str | date | datetime,
    stale_data_threshold_days: int | None = None,
) -> list[tuple[SecurityMasterRecord, FilterDecision]]:
    return [
        (
            record,
            evaluate_security(
                record,
                definition,
                as_of_date=as_of_date,
                stale_data_threshold_days=stale_data_threshold_days,
            ),
        )
        for record in records
    ]


def _canonical_asset_type(record: SecurityMasterRecord) -> str:
    raw = str(record.asset_type or "").strip().upper()
    aliases = {
        "COMMON": "COMMON_STOCK",
        "COMMON STOCK": "COMMON_STOCK",
        "COMMON_STOCK": "COMMON_STOCK",
        "COMMON_STOCK_CANDIDATE": "COMMON_STOCK",
        "REIT": "REIT_COMMON_EQUITY",
        "REIT_COMMON_EQUITY": "REIT_COMMON_EQUITY",
        "ADR_DEPOSITARY": "ADR",
        "PREFERRED_SHARE": "PREFERRED",
        "WARRANTS": "WARRANT",
        "UNITS": "UNIT",
        "CLOSED_END_FUND": "CLOSED_END_FUND",
        "SPAC_SHELL": "SPAC_SHELL",
    }
    if record.is_etf:
        return "ETF"
    if record.is_adr:
        return "ADR"
    if record.is_preferred:
        return "PREFERRED"
    if record.is_warrant:
        return "WARRANT"
    if record.is_unit:
        return "UNIT"
    if record.is_closed_end_fund:
        return "CLOSED_END_FUND"
    if record.is_spac_shell:
        return "SPAC_SHELL"
    if record.is_reit and raw in {"", "COMMON_STOCK", "REIT_COMMON_EQUITY"}:
        return "REIT_COMMON_EQUITY"
    return aliases.get(raw, raw or "UNKNOWN")


def _excluded_asset_type(record: SecurityMasterRecord, asset_type: str, excluded: tuple[str, ...]) -> str | None:
    if asset_type in excluded:
        return asset_type
    for configured_type, flag_name in EXCLUSION_FLAG_BY_ASSET_TYPE.items():
        if configured_type in excluded and bool(getattr(record, flag_name)):
            return configured_type
    return None


def _stale_reason(record: SecurityMasterRecord, as_of_date: str | date | datetime, threshold_days: int) -> str | None:
    if not record.last_updated:
        return "missing_last_updated"
    try:
        last = datetime.fromisoformat(str(record.last_updated).replace("Z", "+00:00")).date()
        current = datetime.fromisoformat(str(as_of_date)).date() if isinstance(as_of_date, str) else as_of_date
        if isinstance(current, datetime):
            current_date = current.date()
        else:
            current_date = current
    except ValueError:
        return "invalid_last_updated"
    if (current_date - last).days > threshold_days:
        return "stale_data"
    return None
