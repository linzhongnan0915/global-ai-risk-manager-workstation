"""Typed models for universe security master, membership, and snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any


def _iso(value: date | datetime | str | None) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class SecurityMasterRecord:
    security_id: str
    ticker: str
    company_name: str = ""
    exchange: str = ""
    asset_type: str = "COMMON_STOCK"
    country: str = "US"
    currency: str = "USD"
    sector: str = ""
    industry: str = ""
    market_cap: float | None = None
    price: float | None = None
    adv_20d: float | None = None
    adv_60d: float | None = None
    ipo_date: str | None = None
    delisting_date: str | None = None
    is_active: bool = True
    is_common_stock: bool = True
    is_adr: bool = False
    is_etf: bool = False
    is_reit: bool = False
    is_preferred: bool = False
    is_warrant: bool = False
    is_unit: bool = False
    is_closed_end_fund: bool = False
    is_spac_shell: bool = False
    data_source: str = "UNKNOWN"
    last_updated: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecurityMasterRecord":
        ticker = str(data.get("ticker") or data.get("symbol") or data.get("symbol_normalized") or "").strip().upper()
        security_id = str(data.get("security_id") or data.get("stable_security_id") or ticker).strip()
        if not ticker:
            raise ValueError("SecurityMasterRecord requires ticker")
        if not security_id:
            raise ValueError("SecurityMasterRecord requires security_id")
        return cls(
            security_id=security_id,
            ticker=ticker,
            company_name=str(data.get("company_name") or data.get("security_name") or ""),
            exchange=str(data.get("exchange") or data.get("listing_exchange") or ""),
            asset_type=str(data.get("asset_type") or data.get("classification") or "COMMON_STOCK").upper(),
            country=str(data.get("country") or "US"),
            currency=str(data.get("currency") or "USD"),
            sector=str(data.get("sector") or ""),
            industry=str(data.get("industry") or ""),
            market_cap=_float_or_none(data.get("market_cap")),
            price=_float_or_none(data.get("price") or data.get("close")),
            adv_20d=_float_or_none(data.get("adv_20d") or data.get("avg_dollar_volume_20d")),
            adv_60d=_float_or_none(data.get("adv_60d") or data.get("avg_dollar_volume_60d")),
            ipo_date=_iso(data.get("ipo_date")),
            delisting_date=_iso(data.get("delisting_date")),
            is_active=_bool(data.get("is_active", True)),
            is_common_stock=_bool(data.get("is_common_stock", data.get("asset_type", "COMMON_STOCK") == "COMMON_STOCK")),
            is_adr=_bool(data.get("is_adr")),
            is_etf=_bool(data.get("is_etf") or data.get("etf_flag") == "Y"),
            is_reit=_bool(data.get("is_reit") or data.get("asset_type") == "REIT_COMMON_EQUITY"),
            is_preferred=_bool(data.get("is_preferred")),
            is_warrant=_bool(data.get("is_warrant")),
            is_unit=_bool(data.get("is_unit")),
            is_closed_end_fund=_bool(data.get("is_closed_end_fund")),
            is_spac_shell=_bool(data.get("is_spac_shell")),
            data_source=str(data.get("data_source") or data.get("source") or "UNKNOWN"),
            last_updated=_iso(data.get("last_updated") or data.get("as_of_date")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UniverseMembershipRecord:
    universe_name: str
    security_id: str
    ticker: str
    membership_start_date: str
    membership_end_date: str | None
    as_of_date: str
    source: str
    version: str
    inclusion_reason: str = "included"
    exclusion_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UniverseSnapshot:
    universe_name: str
    as_of_date: str
    version: str
    total_candidates: int
    included_count: int
    excluded_count: int
    included_tickers: list[str] = field(default_factory=list)
    excluded_by_reason: dict[str, int] = field(default_factory=dict)
    sector_counts: dict[str, int] = field(default_factory=dict)
    market_cap_summary: dict[str, float | int | None] = field(default_factory=dict)
    liquidity_summary: dict[str, float | int | None] = field(default_factory=dict)
    data_quality_warnings: list[str] = field(default_factory=list)
    data_source: str = "UNKNOWN"
    point_in_time_status: str = "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"
    research_use: str = "PROTOTYPE_ONLY"
    not_survivor_bias_free: bool = True
    last_refresh_time: str | None = None
    coverage_summary: dict[str, Any] = field(default_factory=dict)
    asset_type_distribution: dict[str, int] = field(default_factory=dict)
    exchange_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
