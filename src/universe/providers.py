"""Universe data provider interfaces and provisional implementations."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.universe.models import SecurityMasterRecord
from src.universe.security_master import dedupe_security_master


@dataclass(frozen=True)
class ProviderResponse:
    records: list[SecurityMasterRecord] = field(default_factory=list)
    status: str = "UNAVAILABLE"
    source: str = "UNKNOWN"
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
            "record_count": len(self.records),
        }


class UniverseDataProvider:
    """Base provider seam for boss API, local artifacts, and provisional fallback data."""

    source_name = "base_provider"

    def fetch_security_master_candidates(self, *, as_of_date: str | None = None) -> ProviderResponse:
        raise NotImplementedError

    def fetch_index_membership(self, universe_name: str, *, as_of_date: str | None = None) -> ProviderResponse:
        return ProviderResponse(
            status="UNAVAILABLE",
            source=self.source_name,
            warnings=[f"index membership unavailable for {universe_name}"],
        )

    def fetch_prices_and_volume(self, tickers: list[str], *, as_of_date: str | None = None) -> ProviderResponse:
        return ProviderResponse(
            status="UNAVAILABLE",
            source=self.source_name,
            warnings=[f"price/volume unavailable for {len(tickers)} tickers"],
        )

    def fetch_market_cap(self, tickers: list[str], *, as_of_date: str | None = None) -> ProviderResponse:
        return ProviderResponse(
            status="UNAVAILABLE",
            source=self.source_name,
            warnings=[f"market cap unavailable for {len(tickers)} tickers"],
        )

    def fetch_sector_industry(self, tickers: list[str], *, as_of_date: str | None = None) -> ProviderResponse:
        return ProviderResponse(
            status="UNAVAILABLE",
            source=self.source_name,
            warnings=[f"sector/industry unavailable for {len(tickers)} tickers"],
        )


class BossApiUniverseProvider(UniverseDataProvider):
    """Placeholder for the future boss-provided universe API."""

    source_name = "boss_provided_api"

    def __init__(self) -> None:
        self.endpoint = os.getenv("BOSS_UNIVERSE_API_URL") or os.getenv("RMP_UNIVERSE_API_URL")
        self.api_key = os.getenv("BOSS_UNIVERSE_API_KEY") or os.getenv("RMP_UNIVERSE_API_KEY")

    def fetch_security_master_candidates(self, *, as_of_date: str | None = None) -> ProviderResponse:
        if not self.endpoint:
            return ProviderResponse(
                status="UNAVAILABLE",
                source=self.source_name,
                warnings=["Boss universe API endpoint is not configured."],
                metadata={"env_endpoint": "BOSS_UNIVERSE_API_URL or RMP_UNIVERSE_API_URL"},
            )
        return ProviderResponse(
            status="UNAVAILABLE_TODO",
            source=self.source_name,
            warnings=[
                "Boss universe API endpoint is configured, but the adapter contract is not implemented in this release.",
                "No data was fetched or fabricated.",
            ],
            metadata={"endpoint_configured": True, "api_key_configured": bool(self.api_key)},
        )


class ExistingArtifactUniverseProvider(UniverseDataProvider):
    """Read committed local artifacts without pretending they are complete PIT data."""

    source_name = "existing_internal_artifacts"

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root)

    def fetch_security_master_candidates(self, *, as_of_date: str | None = None) -> ProviderResponse:
        as_of = as_of_date or date.today().isoformat()
        records: list[SecurityMasterRecord] = []
        warnings: list[str] = []

        records.extend(self._records_from_sp500_current(as_of, warnings))
        records.extend(self._records_from_worldquant_reference(warnings))
        deduped = dedupe_security_master(records)
        status = "LOADED_CURRENT_MEMBERSHIP_ONLY_PROVISIONAL" if deduped else "UNAVAILABLE"
        if deduped:
            warnings.append("Existing artifacts are current membership or research candidate artifacts, not true historical PIT membership.")
        else:
            warnings.append("No committed security master or current constituent artifacts were found.")
        return ProviderResponse(
            records=deduped,
            status=status,
            source=self.source_name,
            warnings=warnings,
            metadata={
                "sp500_current_path": "dashboard/data/universes/sp500_current.json",
                "worldquant_master_path": "data/reference/worldquant_alpha2_us_security_master.csv",
                "worldquant_research_path": "data/reference/worldquant_alpha2_research_universe_v1.csv",
            },
        )

    def _records_from_sp500_current(self, as_of: str, warnings: list[str]) -> list[SecurityMasterRecord]:
        path = self.root / "dashboard/data/universes/sp500_current.json"
        if not path.exists():
            warnings.append("S&P 500 current artifact not found.")
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        artifact_as_of = str(payload.get("as_of_date") or as_of)
        rows = payload.get("constituents") or []
        records = [
            SecurityMasterRecord(
                security_id=f"SP500_CURRENT:{str(row.get('ticker', '')).strip().upper()}",
                ticker=str(row.get("ticker", "")).strip().upper(),
                company_name=str(row.get("company_name") or ""),
                exchange="",
                asset_type="COMMON_STOCK",
                country="US",
                currency="USD",
                sector=str(row.get("sector") or ""),
                industry=str(row.get("industry") or ""),
                data_source="existing_internal_artifact:sp500_current_current_membership_only",
                last_updated=artifact_as_of,
            )
            for row in rows
            if str(row.get("ticker") or "").strip()
        ]
        warnings.append(
            "S&P 500 current artifact supplies current constituents and sector/industry labels only; price, ADV, market cap, and historical membership are unavailable."
        )
        return records

    def _records_from_worldquant_reference(self, warnings: list[str]) -> list[SecurityMasterRecord]:
        for relative in (
            "data/reference/worldquant_alpha2_research_universe_v1.csv",
            "data/reference/worldquant_alpha2_us_security_master.csv",
        ):
            path = self.root / relative
            if path.exists():
                frame = pd.read_csv(path)
                warnings.append(f"Loaded WorldQuant reference artifact: {relative}")
                return [
                    SecurityMasterRecord.from_dict(
                        {
                            **row,
                            "security_id": row.get("symbol_normalized") or row.get("symbol_raw"),
                            "ticker": row.get("symbol_normalized") or row.get("symbol_raw"),
                            "company_name": row.get("security_name", ""),
                            "exchange": row.get("listing_exchange", ""),
                            "asset_type": _asset_type_from_worldquant(row),
                            "is_common_stock": row.get("classification") == "common_stock",
                            "is_reit": row.get("classification") == "reit_common_equity",
                            "is_adr": row.get("is_adr", False),
                            "data_source": f"existing_internal_artifact:{relative}",
                        }
                    )
                    for row in frame.to_dict(orient="records")
                    if row.get("symbol_normalized") or row.get("symbol_raw")
                ]
        warnings.append("WorldQuant reference security master artifacts not found.")
        return []


class PublicFallbackUniverseProvider(UniverseDataProvider):
    """Optional provisional fallback placeholder; not production-grade membership."""

    source_name = "PROVISIONAL_PUBLIC_FALLBACK"

    def fetch_security_master_candidates(self, *, as_of_date: str | None = None) -> ProviderResponse:
        return ProviderResponse(
            status="UNAVAILABLE_PROVISIONAL_ONLY",
            source=self.source_name,
            warnings=[
                "Public/yfinance fallback is intentionally not used as final production-grade membership.",
                "Implement only as a temporary price/volume enrichment source after explicit approval.",
            ],
        )


class PrioritizedUniverseProvider(UniverseDataProvider):
    """Try providers in source-priority order and return the first provider with records."""

    source_name = "prioritized_provider_chain"

    def __init__(self, providers: list[UniverseDataProvider]) -> None:
        self.providers = providers

    def fetch_security_master_candidates(self, *, as_of_date: str | None = None) -> ProviderResponse:
        statuses: list[dict[str, Any]] = []
        warnings: list[str] = []
        for provider in self.providers:
            result = provider.fetch_security_master_candidates(as_of_date=as_of_date)
            statuses.append(result.to_dict())
            warnings.extend(result.warnings)
            if result.records:
                return ProviderResponse(
                    records=result.records,
                    status=result.status,
                    source=result.source,
                    warnings=warnings,
                    metadata={"provider_chain": statuses},
                )
        return ProviderResponse(
            status="UNAVAILABLE",
            source=self.source_name,
            warnings=warnings or ["No provider returned security master candidates."],
            metadata={"provider_chain": statuses},
        )


def default_universe_provider(root: str | Path = ".") -> UniverseDataProvider:
    return PrioritizedUniverseProvider(
        [
            BossApiUniverseProvider(),
            ExistingArtifactUniverseProvider(root),
            PublicFallbackUniverseProvider(),
        ]
    )


def _asset_type_from_worldquant(row: dict[str, Any]) -> str:
    classification = str(row.get("classification") or "").strip().lower()
    if classification == "reit_common_equity":
        return "REIT_COMMON_EQUITY"
    if classification == "common_stock":
        return "COMMON_STOCK"
    reason = str(row.get("exclusion_reason") or "").strip().lower()
    mapping = {
        "etf_flag": "ETF",
        "adr_depositary": "ADR",
        "preferred_share": "PREFERRED",
        "warrant": "WARRANT",
        "warrants": "WARRANT",
        "unit": "UNIT",
        "units": "UNIT",
        "closed_end_fund": "CLOSED_END_FUND",
        "spac_shell": "SPAC_SHELL",
    }
    return mapping.get(reason, classification.upper() or "UNKNOWN")
