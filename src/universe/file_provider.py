"""File-based universe provider for staged boss/API data extracts."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.universe.models import SecurityMasterRecord
from src.universe.provider_validation import (
    INDEX_MEMBERSHIP_SPEC,
    PRICE_VOLUME_SNAPSHOT_SPEC,
    SECTOR_INDUSTRY_SPEC,
    SECURITY_MASTER_SPEC,
    ProviderValidationError,
    ValidatedProviderTable,
    load_and_validate_provider_table,
    table_metadata,
    validation_warnings,
)
from src.universe.providers import ProviderResponse, UniverseDataProvider
from src.universe.security_master import dedupe_security_master, normalize_ticker

DEFAULT_FILE_PROVIDER_INPUT_DIR = Path("data/provider_inputs/universe")


class FileUniverseProvider(UniverseDataProvider):
    """Load validated universe inputs from CSV or parquet files."""

    source_name = "file_provider"

    def __init__(self, input_dir: str | Path = DEFAULT_FILE_PROVIDER_INPUT_DIR, *, allow_parquet: bool = True) -> None:
        self.input_dir = Path(input_dir)
        self.allow_parquet = allow_parquet

    def fetch_security_master_candidates(self, *, as_of_date: str | None = None) -> ProviderResponse:
        as_of = as_of_date or date.today().isoformat()
        metadata: dict[str, Any] = {
            "input_dir": str(self.input_dir),
            "allow_parquet": self.allow_parquet,
            "tables": {},
            "validation_issues": [],
        }
        warnings: list[str] = []

        try:
            master = self._load_table(SECURITY_MASTER_SPEC, metadata, warnings)
            prices = self._load_table(PRICE_VOLUME_SNAPSHOT_SPEC, metadata, warnings)
            sectors = self._load_table(SECTOR_INDUSTRY_SPEC, metadata, warnings)
            membership = self._load_table(INDEX_MEMBERSHIP_SPEC, metadata, warnings)
        except ProviderValidationError:
            raise

        if master is None:
            warnings.append("security_master.csv is unavailable; file provider has no production candidate base.")
            return ProviderResponse(
                status="UNAVAILABLE",
                source=self.source_name,
                warnings=warnings,
                metadata=metadata,
            )
        if master.frame.empty:
            warnings.append("security_master provider file has no valid non-template production rows.")
            return ProviderResponse(
                status="NO_VALID_SECURITY_MASTER_ROWS",
                source=self.source_name,
                warnings=warnings,
                metadata=metadata,
            )

        records = self._records_from_tables(
            master.frame,
            prices.frame if prices else None,
            sectors.frame if sectors else None,
            membership.frame if membership else None,
            as_of_date=as_of,
            warnings=warnings,
        )
        records = dedupe_security_master(records)
        if prices is None:
            warnings.append("prices_volume_snapshot.csv is unavailable; price, ADV, and market cap gates will exclude candidates.")
        if sectors is None:
            warnings.append("sector_industry.csv is unavailable; sector coverage will be incomplete.")
        if membership is None:
            warnings.append("index_membership.csv is unavailable; security_master rows are treated as current candidates only.")
        warnings.append("Point-in-time status remains CURRENT_MEMBERSHIP_ONLY_PROVISIONAL unless historical membership is approved.")

        status = "LOADED_FILE_PROVIDER" if records else "NO_VALID_FILE_PROVIDER_RECORDS"
        return ProviderResponse(
            records=records,
            status=status,
            source=self.source_name,
            warnings=warnings,
            metadata=metadata,
        )

    def _load_table(
        self,
        spec,
        metadata: dict[str, Any],
        warnings: list[str],
    ) -> ValidatedProviderTable | None:
        table = load_and_validate_provider_table(self.input_dir, spec, allow_parquet=self.allow_parquet)
        metadata["tables"][spec.stem] = table_metadata(table) or {"path": None, "valid_rows": 0, "rejected_rows": 0}
        if table is None:
            warnings.append(f"{spec.stem} file not found in {self.input_dir}.")
            return None
        issue_payloads = [issue.to_dict() for issue in table.issues]
        metadata["validation_issues"].extend(issue_payloads)
        warnings.extend(validation_warnings(table.issues))
        if table.rejected_rows:
            warnings.append(f"{spec.stem}: rejected {table.rejected_rows} invalid or template rows.")
        return table

    def _records_from_tables(
        self,
        master: pd.DataFrame,
        prices: pd.DataFrame | None,
        sectors: pd.DataFrame | None,
        membership: pd.DataFrame | None,
        *,
        as_of_date: str,
        warnings: list[str],
    ) -> list[SecurityMasterRecord]:
        price_by_id, price_by_ticker = _index_rows(prices, "prices_volume_snapshot", warnings)
        sector_by_id, sector_by_ticker = _index_rows(sectors, "sector_industry", warnings)
        active_membership_ids = _active_membership_ids(membership, as_of_date, warnings)
        membership_by_id, membership_by_ticker = _index_rows(membership, "index_membership", warnings)

        records: list[SecurityMasterRecord] = []
        for row in master.to_dict(orient="records"):
            security_id = str(row.get("security_id") or "").strip()
            ticker = normalize_ticker(str(row.get("ticker") or ""))
            if active_membership_ids is not None and security_id not in active_membership_ids:
                continue

            price_row = _lookup_row(price_by_id, price_by_ticker, security_id, ticker)
            sector_row = _lookup_row(sector_by_id, sector_by_ticker, security_id, ticker)
            membership_row = _lookup_row(membership_by_id, membership_by_ticker, security_id, ticker)
            merged = dict(row)
            merged["ticker"] = ticker
            if price_row:
                _copy_fields(
                    merged,
                    price_row,
                    ("price", "adv_20d", "adv_60d", "market_cap", "currency", "last_updated"),
                    overwrite=True,
                )
            if sector_row:
                _copy_fields(merged, sector_row, ("sector", "industry", "last_updated"), overwrite=False)
            if membership_row:
                merged["membership_index_name"] = membership_row.get("index_name")
            merged["data_source"] = _source_label(row, price_row, sector_row, membership_row)
            records.append(SecurityMasterRecord.from_dict(merged))
        return records


def _index_rows(
    frame: pd.DataFrame | None,
    table_name: str,
    warnings: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_ticker: dict[str, dict[str, Any]] = {}
    if frame is None or frame.empty:
        return by_id, by_ticker
    duplicate_ids = frame["security_id"].astype(str).duplicated(keep="last") if "security_id" in frame else pd.Series(dtype=bool)
    duplicate_tickers = frame["ticker"].astype(str).map(normalize_ticker).duplicated(keep="last") if "ticker" in frame else pd.Series(dtype=bool)
    if bool(duplicate_ids.any()):
        warnings.append(f"{table_name}: duplicate security_id rows found; last row is used for enrichment.")
    if bool(duplicate_tickers.any()):
        warnings.append(f"{table_name}: duplicate ticker rows found; last row is used as fallback enrichment.")
    for row in frame.to_dict(orient="records"):
        security_id = str(row.get("security_id") or "").strip()
        ticker = normalize_ticker(str(row.get("ticker") or ""))
        if security_id:
            by_id[security_id] = row
        if ticker:
            by_ticker[ticker] = row
    return by_id, by_ticker


def _active_membership_ids(
    membership: pd.DataFrame | None,
    as_of_date: str,
    warnings: list[str],
) -> set[str] | None:
    if membership is None:
        return None
    if membership.empty:
        warnings.append("index_membership.csv has no valid rows; no membership-filtered candidates are available.")
        return set()
    as_of = pd.Timestamp(as_of_date)
    start = pd.to_datetime(membership["membership_start_date"], errors="coerce")
    if "membership_end_date" in membership.columns:
        end = pd.to_datetime(membership["membership_end_date"], errors="coerce")
    else:
        end = pd.Series([pd.NaT] * len(membership), index=membership.index)
    active = start.le(as_of) & (end.isna() | end.gt(as_of))
    active_frame = membership.loc[active]
    if active_frame.empty:
        warnings.append(f"index_membership.csv has no active rows as of {as_of_date}.")
    return {str(value).strip() for value in active_frame["security_id"].tolist() if str(value).strip()}


def _lookup_row(
    by_id: dict[str, dict[str, Any]],
    by_ticker: dict[str, dict[str, Any]],
    security_id: str,
    ticker: str,
) -> dict[str, Any] | None:
    return by_id.get(security_id) or by_ticker.get(ticker)


def _copy_fields(
    target: dict[str, Any],
    source: dict[str, Any],
    fields: tuple[str, ...],
    *,
    overwrite: bool,
) -> None:
    for field in fields:
        value = source.get(field)
        if value is None or value == "":
            continue
        if overwrite or target.get(field) in {None, ""}:
            target[field] = value


def _source_label(
    master_row: dict[str, Any],
    price_row: dict[str, Any] | None,
    sector_row: dict[str, Any] | None,
    membership_row: dict[str, Any] | None,
) -> str:
    parts = [f"master={master_row.get('data_source') or 'UNKNOWN'}"]
    if price_row:
        parts.append(f"price={price_row.get('data_source') or 'UNKNOWN'}")
    if sector_row:
        parts.append(f"sector={sector_row.get('data_source') or 'UNKNOWN'}")
    if membership_row:
        index_name = membership_row.get("index_name") or "UNKNOWN_INDEX"
        parts.append(f"membership={index_name}:{membership_row.get('data_source') or 'UNKNOWN'}")
    return "file_provider:" + ";".join(str(part) for part in parts)
