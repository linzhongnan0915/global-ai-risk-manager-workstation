"""Provisional yfinance/public fallback provider for universe population.

This provider is explicitly prototype-only. It builds current-listed candidate
pools from committed reference artifacts or existing symbol-directory utilities,
then enriches candidates with recent yfinance price/volume and best-effort
fundamental fields. It is not point-in-time, not survivor-bias-free, and not an
institutional data replacement.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.strategies.worldquant.research_universe import filter_research_universe_v1
from src.strategies.worldquant.universe import build_universe_from_download
from src.universe.models import SecurityMasterRecord
from src.universe.providers import ProviderResponse, UniverseDataProvider
from src.universe.security_master import dedupe_security_master, normalize_ticker, records_from_dataframe, records_to_dataframe
from src.universe.universe_definitions import DEFAULT_DEFINITIONS_PATH, load_universe_config

DATA_SOURCE = "YFINANCE_PUBLIC_FALLBACK"
POINT_IN_TIME_STATUS = "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"
RESEARCH_USE = "PROTOTYPE_ONLY"
NOT_SURVIVOR_BIAS_FREE = True

BROAD_UNIVERSES = {
    "US_BROAD_MARKET",
    "US_SMALL_CAP",
    "US_ALL_COMMON_RESEARCH",
    "US_TRADABLE_LIQUID",
}
LARGE_CAP_UNIVERSE = "US_LARGE_CAP_CORE"


class YFinanceProvisionalUniverseProvider(UniverseDataProvider):
    """Generate provisional current-membership-only universe candidates."""

    source_name = DATA_SOURCE

    def __init__(
        self,
        root: str | Path = ".",
        *,
        definitions_path: str | Path | None = None,
        max_tickers: int | None = None,
        universe_names: list[str] | tuple[str, ...] | None = None,
        chunk_size: int | None = None,
        use_cache: bool = True,
        force_refresh: bool = False,
        allow_symbol_directory_download: bool = True,
        yfinance_module: Any | None = None,
        fundamentals_max_tickers: int | None = None,
        sleep_seconds: float = 0.0,
    ) -> None:
        self.root = Path(root)
        self.definitions_path = Path(definitions_path) if definitions_path else self.root / DEFAULT_DEFINITIONS_PATH
        self.max_tickers = max_tickers
        self.universe_names = tuple(universe_names) if universe_names else None
        self.chunk_size = chunk_size
        self.use_cache = use_cache
        self.force_refresh = force_refresh
        self.allow_symbol_directory_download = allow_symbol_directory_download
        self.yfinance = yfinance_module
        self.fundamentals_max_tickers = fundamentals_max_tickers
        self.sleep_seconds = sleep_seconds
        self.cache_dir = self.root / "data" / "universe" / "cache"
        self.diagnostics_path = self.root / "data" / "universe" / "yfinance_provisional_diagnostics.json"

    def fetch_security_master_candidates(self, *, as_of_date: str | None = None) -> ProviderResponse:
        as_of = as_of_date or date.today().isoformat()
        generated_at = datetime.now(timezone.utc).isoformat()
        config = load_universe_config(self.definitions_path)
        settings = config.global_settings
        requested_universes = self._requested_universes(config.definitions.keys())
        chunk_size = int(self.chunk_size or settings.get("chunk_size") or 250)
        max_tickers = int(self.max_tickers or settings.get("max_universe_size") or 5000)
        price_period = str(settings.get("yfinance_price_period") or "4mo")
        retry_policy = settings.get("retry_policy") or {}
        fundamentals_limit = int(
            self.fundamentals_max_tickers
            or settings.get("yfinance_fundamentals_max_tickers")
            or max_tickers
        )

        warnings: list[str] = [
            "YFinance/public fallback data is prototype-only and not institutional-grade.",
            "This universe is current-membership-only and not survivor-bias-free.",
            "The broad research pool is not a direct optimizer/trading universe; use US_TRADABLE_LIQUID or approved strategy-specific universes for that purpose.",
        ]
        metadata: dict[str, Any] = {
            "data_source": DATA_SOURCE,
            "point_in_time_status": POINT_IN_TIME_STATUS,
            "research_use": RESEARCH_USE,
            "not_survivor_bias_free": NOT_SURVIVOR_BIAS_FREE,
            "requested_universes": list(requested_universes),
            "max_tickers": max_tickers,
            "chunk_size": chunk_size,
            "price_period": price_period,
            "candidate_sources": {},
            "universe_candidate_tickers": {},
            "chunk_statuses": [],
            "ticker_failures": [],
            "field_warning_counts": {},
        }

        needs_broad = any(name in BROAD_UNIVERSES for name in requested_universes)
        needs_sp500 = LARGE_CAP_UNIVERSE in requested_universes or needs_broad
        sp500_records = self._load_sp500_current_records(as_of, warnings, metadata) if needs_sp500 else []
        broad_records = self._load_broad_current_listed_records(as_of, warnings, metadata) if needs_broad else []
        if needs_broad and broad_records:
            broad_records = self._merge_sp500_enrichment_into_broad(sp500_records, broad_records)

        candidates_by_universe = self._candidate_records_by_universe(
            requested_universes,
            sp500_records=sp500_records,
            broad_records=broad_records,
            max_tickers=max_tickers,
        )
        metadata["universe_candidate_tickers"] = {
            name: [record.ticker for record in records] for name, records in candidates_by_universe.items()
        }
        metadata["candidate_sources"]["candidate_counts_by_universe"] = {
            name: len(records) for name, records in candidates_by_universe.items()
        }
        base_records = dedupe_security_master(
            record for records in candidates_by_universe.values() for record in records
        )
        if not base_records:
            warnings.append("No current-listed candidate records were available for the requested universes.")
            response = ProviderResponse(
                records=[],
                status="UNAVAILABLE_NO_CURRENT_LISTED_CANDIDATES",
                source=DATA_SOURCE,
                warnings=warnings,
                metadata=metadata,
            )
            self._write_diagnostics(response, as_of, generated_at)
            return response

        cached = self._load_cached_records(as_of, base_records, warnings)
        if cached is not None:
            records = cached
            status = "LOADED_YFINANCE_PUBLIC_FALLBACK_PROVISIONAL_FROM_CACHE"
        else:
            cached_by_ticker = self._load_partial_cached_records(as_of, base_records, warnings)
            records_to_fetch = [record for record in base_records if record.ticker not in cached_by_ticker]
            if cached_by_ticker:
                metadata["partial_cache_hit_count"] = len(cached_by_ticker)
                metadata["partial_cache_miss_count"] = len(records_to_fetch)
            yf_module = self._load_yfinance(warnings)
            if not records_to_fetch:
                records = [cached_by_ticker[record.ticker] for record in base_records]
                status = "LOADED_YFINANCE_PUBLIC_FALLBACK_PROVISIONAL_FROM_PARTIAL_CACHE"
            elif yf_module is None:
                fetched_records = self._records_without_yfinance(records_to_fetch, as_of)
                by_ticker = {record.ticker: record for record in fetched_records}
                records = [cached_by_ticker.get(record.ticker) or by_ticker[record.ticker] for record in base_records]
                status = "YFINANCE_UNAVAILABLE_CANDIDATES_ONLY"
            else:
                price_rows, price_failures = self._fetch_price_volume_rows(
                    records_to_fetch,
                    yf_module,
                    chunk_size=chunk_size,
                    price_period=price_period,
                    retry_policy=retry_policy,
                    metadata=metadata,
                )
                fundamentals = self._fetch_fundamental_rows(
                    records_to_fetch,
                    yf_module,
                    limit=fundamentals_limit,
                    metadata=metadata,
                )
                fetched_records = self._merge_enrichment(
                    records_to_fetch,
                    price_rows,
                    fundamentals,
                    as_of_date=as_of,
                    warnings=warnings,
                    metadata=metadata,
                )
                fetched_by_ticker = {record.ticker: record for record in fetched_records}
                records = [cached_by_ticker.get(record.ticker) or fetched_by_ticker[record.ticker] for record in base_records]
                self._write_cached_records(as_of, base_records, records, warnings)
                status = self._status_from_enrichment(records, price_failures)

        coverage = self._coverage(records)
        metadata["coverage"] = coverage
        metadata["field_warning_counts"] = self._field_warning_counts(records)
        warnings.extend(self._coverage_warnings(metadata["field_warning_counts"], len(records)))
        response = ProviderResponse(
            records=records,
            status=status,
            source=DATA_SOURCE,
            warnings=sorted(set(warnings)),
            metadata=metadata,
        )
        self._write_diagnostics(response, as_of, generated_at)
        return response

    def _requested_universes(self, available: Any) -> tuple[str, ...]:
        available_set = {str(name) for name in available}
        if self.universe_names is None:
            return tuple(name for name in (LARGE_CAP_UNIVERSE, *sorted(BROAD_UNIVERSES)) if name in available_set)
        requested = tuple(str(name) for name in self.universe_names)
        unknown = [name for name in requested if name not in available_set]
        if unknown:
            raise ValueError(f"unknown universe(s): {unknown}")
        return requested

    def _load_sp500_current_records(
        self,
        as_of_date: str,
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> list[SecurityMasterRecord]:
        path = self.root / "dashboard" / "data" / "universes" / "sp500_current.json"
        if not path.exists():
            warnings.append("S&P 500 current reference artifact not found.")
            metadata["candidate_sources"]["sp500_current"] = {"path": str(path), "count": 0}
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("constituents") or []
        artifact_as_of = str(payload.get("as_of_date") or as_of_date)
        records = [
            SecurityMasterRecord(
                security_id=f"SP500_CURRENT:{normalize_ticker(row.get('ticker'))}",
                ticker=normalize_ticker(str(row.get("ticker") or "")),
                company_name=str(row.get("company_name") or ""),
                exchange="",
                asset_type="COMMON_STOCK",
                country="US",
                currency="USD",
                sector=str(row.get("sector") or ""),
                industry=str(row.get("industry") or ""),
                data_source=DATA_SOURCE,
                last_updated=artifact_as_of,
            )
            for row in rows
            if str(row.get("ticker") or "").strip()
        ]
        metadata["candidate_sources"]["sp500_current"] = {
            "path": str(path),
            "count": len(records),
            "as_of_date": artifact_as_of,
            "status": "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL",
        }
        warnings.append("US_LARGE_CAP_CORE uses the current S&P 500 reference artifact when available; this is not historical index membership.")
        return records

    def _load_broad_current_listed_records(
        self,
        as_of_date: str,
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> list[SecurityMasterRecord]:
        artifact_records = self._load_worldquant_reference_records(as_of_date, warnings, metadata)
        if artifact_records:
            return artifact_records
        if not self.allow_symbol_directory_download:
            warnings.append("Current-listed broad security master artifacts were not found; symbol-directory download is disabled.")
            return []
        try:
            master, _, summary = build_universe_from_download()
            research = filter_research_universe_v1(master)
        except Exception as exc:
            warnings.append(f"Current-listed broad security master download failed: {type(exc).__name__}: {exc}")
            metadata["candidate_sources"]["nasdaq_trader_symbol_directory"] = {
                "status": "DOWNLOAD_FAILED",
                "error": f"{type(exc).__name__}: {exc}",
            }
            return []
        records = self._records_from_current_listed_frame(research, as_of_date)
        metadata["candidate_sources"]["nasdaq_trader_symbol_directory"] = {
            "status": "DOWNLOADED_CURRENT_LISTED",
            "count": len(records),
            "summary": summary,
        }
        warnings.append("Broad candidate pool was generated from current Nasdaq Trader symbol-directory utilities; historical delistings are absent.")
        return records

    def _load_worldquant_reference_records(
        self,
        as_of_date: str,
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> list[SecurityMasterRecord]:
        paths = [
            self.root / "data" / "reference" / "worldquant_alpha2_research_universe_v1.csv",
            self.root / "data" / "reference" / "worldquant_alpha2_common_stock_candidates.csv",
            self.root / "data" / "reference" / "worldquant_alpha2_us_security_master.csv",
        ]
        for path in paths:
            if not path.exists():
                continue
            frame = pd.read_csv(path)
            if "eligible_candidate" in frame.columns and "classification" in frame.columns:
                try:
                    frame = filter_research_universe_v1(frame)
                except ValueError:
                    frame = frame.loc[frame["eligible_candidate"].astype(bool)].copy()
            records = self._records_from_current_listed_frame(frame, as_of_date)
            metadata["candidate_sources"]["worldquant_current_listed_artifact"] = {
                "path": str(path),
                "count": len(records),
            }
            warnings.append(f"Loaded broad current-listed candidate artifact: {path.relative_to(self.root)}")
            return records
        warnings.append("Broad current-listed WorldQuant security master artifacts were not found.")
        metadata["candidate_sources"]["worldquant_current_listed_artifact"] = {"count": 0}
        return []

    def _records_from_current_listed_frame(self, frame: pd.DataFrame, as_of_date: str) -> list[SecurityMasterRecord]:
        records: list[SecurityMasterRecord] = []
        for row in frame.to_dict(orient="records"):
            ticker = normalize_ticker(
                str(row.get("symbol_normalized") or row.get("symbol_raw") or row.get("ticker") or "")
            )
            if not ticker:
                continue
            classification = str(row.get("classification") or "").strip().lower()
            if classification not in {"common_stock", "reit_common_equity", "common_stock_candidate", ""}:
                continue
            is_reit = classification == "reit_common_equity" or bool(row.get("is_reit"))
            records.append(
                SecurityMasterRecord(
                    security_id=f"CURRENT_LISTED:{ticker}",
                    ticker=ticker,
                    company_name=str(row.get("security_name") or row.get("company_name") or ""),
                    exchange=str(row.get("listing_exchange") or row.get("exchange") or ""),
                    asset_type="REIT_COMMON_EQUITY" if is_reit else "COMMON_STOCK",
                    country="US",
                    currency="USD",
                    is_common_stock=not is_reit,
                    is_reit=is_reit,
                    is_adr=bool(row.get("is_adr")),
                    data_source=DATA_SOURCE,
                    last_updated=as_of_date,
                )
            )
        return records

    def _candidate_records_by_universe(
        self,
        requested_universes: tuple[str, ...],
        *,
        sp500_records: list[SecurityMasterRecord],
        broad_records: list[SecurityMasterRecord],
        max_tickers: int,
    ) -> dict[str, list[SecurityMasterRecord]]:
        candidates: dict[str, list[SecurityMasterRecord]] = {}
        ranked_large = self._rank_records(sp500_records)[:max_tickers]
        ranked_broad = self._rank_records(broad_records)[:max_tickers]
        for universe_name in requested_universes:
            if universe_name == LARGE_CAP_UNIVERSE:
                candidates[universe_name] = ranked_large
            elif universe_name in BROAD_UNIVERSES:
                candidates[universe_name] = ranked_broad
            else:
                candidates[universe_name] = []
        return candidates

    def _merge_sp500_enrichment_into_broad(
        self,
        sp500_records: list[SecurityMasterRecord],
        broad_records: list[SecurityMasterRecord],
    ) -> list[SecurityMasterRecord]:
        """Use current-listed rows as broad-universe membership; S&P rows only enrich metadata."""
        sp500_by_ticker = {record.ticker: record for record in sp500_records}
        merged: list[SecurityMasterRecord] = []
        broad_tickers: set[str] = set()
        for record in broad_records:
            broad_tickers.add(record.ticker)
            sp500 = sp500_by_ticker.get(record.ticker)
            if sp500 is None:
                merged.append(record)
                continue
            merged.append(
                SecurityMasterRecord(
                    **{
                        **record.to_dict(),
                        "company_name": record.company_name or sp500.company_name,
                        "sector": record.sector or sp500.sector,
                        "industry": record.industry or sp500.industry,
                        "data_source": DATA_SOURCE,
                    }
                )
            )
        missing_from_broad = [record for record in sp500_records if record.ticker not in broad_tickers]
        return dedupe_security_master([*merged, *missing_from_broad])

    def _rank_records(self, records: list[SecurityMasterRecord]) -> list[SecurityMasterRecord]:
        exchange_rank = {
            "NASDAQ": 0,
            "NYSE": 1,
            "NYSE AMERICAN": 2,
            "NYSE MKT / AMEX HISTORICAL": 2,
            "BATS": 3,
            "IEX": 4,
        }
        return sorted(
            dedupe_security_master(records),
            key=lambda record: (
                exchange_rank.get(str(record.exchange).upper(), 9),
                record.ticker,
            ),
        )

    def _load_yfinance(self, warnings: list[str]) -> Any | None:
        if self.yfinance is not None:
            return self.yfinance
        try:
            import yfinance as yf
        except Exception as exc:
            warnings.append(f"yfinance import failed: {type(exc).__name__}: {exc}")
            return None
        return yf

    def _fetch_price_volume_rows(
        self,
        records: list[SecurityMasterRecord],
        yf_module: Any,
        *,
        chunk_size: int,
        price_period: str,
        retry_policy: dict[str, Any],
        metadata: dict[str, Any],
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        rows: dict[str, dict[str, Any]] = {}
        failures: list[str] = []
        tickers = [record.ticker for record in records]
        max_attempts = int(retry_policy.get("max_attempts") or 1)
        backoff_seconds = list(retry_policy.get("backoff_seconds") or [0])
        timeout = retry_policy.get("request_timeout_seconds")
        for chunk in _chunks(tickers, max(1, chunk_size)):
            yf_symbols = [_to_yfinance_symbol(ticker) for ticker in chunk]
            data = None
            error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    kwargs = {
                        "tickers": yf_symbols,
                        "period": price_period,
                        "interval": "1d",
                        "auto_adjust": False,
                        "progress": False,
                        "group_by": "ticker",
                        "threads": True,
                    }
                    if timeout is not None:
                        kwargs["timeout"] = timeout
                    data = yf_module.download(**kwargs)
                    error = None
                    break
                except Exception as exc:
                    error = exc
                    if attempt < max_attempts:
                        delay = float(backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)])
                        if delay:
                            time.sleep(delay)
            if error is not None:
                failures.extend(chunk)
                metadata["chunk_statuses"].append(
                    {
                        "tickers": chunk,
                        "status": "FAILED",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
                continue
            chunk_loaded = 0
            for ticker in chunk:
                frame = _extract_ticker_frame(data, _to_yfinance_symbol(ticker))
                normalized = _price_volume_from_frame(frame)
                if normalized is None:
                    failures.append(ticker)
                    continue
                rows[ticker] = normalized
                chunk_loaded += 1
            metadata["chunk_statuses"].append(
                {
                    "tickers": chunk,
                    "status": "LOADED" if chunk_loaded else "NO_USABLE_ROWS",
                    "loaded_tickers": chunk_loaded,
                }
            )
            if self.sleep_seconds:
                time.sleep(self.sleep_seconds)
        metadata["ticker_failures"] = sorted(set(failures))
        return rows, failures

    def _fetch_fundamental_rows(
        self,
        records: list[SecurityMasterRecord],
        yf_module: Any,
        *,
        limit: int,
        metadata: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        failures: list[dict[str, str]] = []
        for record in records[: max(0, limit)]:
            try:
                ticker_obj = yf_module.Ticker(_to_yfinance_symbol(record.ticker))
                fast_info = _safe_mapping(getattr(ticker_obj, "fast_info", {}) or {})
                info = _safe_mapping(getattr(ticker_obj, "info", {}) or {})
                rows[record.ticker] = {
                    "market_cap": _first_float(
                        fast_info,
                        info,
                        keys=("market_cap", "marketCap", "marketcapitalization"),
                    ),
                    "sector": _first_text(info, keys=("sector",)),
                    "industry": _first_text(info, keys=("industry",)),
                    "quote_type": _first_text(info, keys=("quoteType", "quote_type")),
                }
            except Exception as exc:
                failures.append({"ticker": record.ticker, "error": f"{type(exc).__name__}: {exc}"})
        if len(records) > limit:
            metadata["fundamentals_not_requested_count"] = len(records) - limit
        metadata["fundamental_failures"] = failures
        return rows

    def _merge_enrichment(
        self,
        base_records: list[SecurityMasterRecord],
        price_rows: dict[str, dict[str, Any]],
        fundamentals: dict[str, dict[str, Any]],
        *,
        as_of_date: str,
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> list[SecurityMasterRecord]:
        records: list[SecurityMasterRecord] = []
        for base in base_records:
            price_row = price_rows.get(base.ticker) or {}
            fundamental_row = fundamentals.get(base.ticker) or {}
            if not price_row:
                warnings.append(f"{base.ticker}: missing usable yfinance price/volume rows.")
            if fundamental_row and fundamental_row.get("quote_type") in {"ETF", "MUTUALFUND"}:
                warnings.append(f"{base.ticker}: yfinance quoteType={fundamental_row.get('quote_type')} conflicts with common-stock candidate classification.")
            records.append(
                SecurityMasterRecord(
                    **{
                        **base.to_dict(),
                        "market_cap": fundamental_row.get("market_cap") if fundamental_row.get("market_cap") is not None else base.market_cap,
                        "price": price_row.get("price"),
                        "adv_20d": price_row.get("adv_20d"),
                        "adv_60d": price_row.get("adv_60d"),
                        "sector": fundamental_row.get("sector") or base.sector,
                        "industry": fundamental_row.get("industry") or base.industry,
                        "data_source": DATA_SOURCE,
                        "last_updated": price_row.get("latest_date") or as_of_date,
                    }
                )
            )
        metadata["price_rows_loaded"] = len(price_rows)
        metadata["fundamental_rows_loaded"] = len(fundamentals)
        return records

    def _records_without_yfinance(self, base_records: list[SecurityMasterRecord], as_of_date: str) -> list[SecurityMasterRecord]:
        return [
            SecurityMasterRecord(
                **{
                    **record.to_dict(),
                    "price": None,
                    "adv_20d": None,
                    "adv_60d": None,
                    "market_cap": record.market_cap,
                    "data_source": DATA_SOURCE,
                    "last_updated": as_of_date,
                }
            )
            for record in base_records
        ]

    def _load_cached_records(
        self,
        as_of_date: str,
        base_records: list[SecurityMasterRecord],
        warnings: list[str],
    ) -> list[SecurityMasterRecord] | None:
        if self.force_refresh or not self.use_cache:
            return None
        path = self._cache_path(as_of_date, base_records)
        if not path.exists():
            return None
        try:
            records = records_from_dataframe(pd.read_csv(path))
        except Exception as exc:
            warnings.append(f"Failed to read yfinance provisional cache {path}: {type(exc).__name__}: {exc}")
            return None
        warnings.append(f"Loaded yfinance provisional enrichment cache: {path}")
        return records

    def _load_partial_cached_records(
        self,
        as_of_date: str,
        base_records: list[SecurityMasterRecord],
        warnings: list[str],
    ) -> dict[str, SecurityMasterRecord]:
        if self.force_refresh or not self.use_cache or not self.cache_dir.exists():
            return {}
        wanted = {record.ticker for record in base_records}
        cached: dict[str, SecurityMasterRecord] = {}
        for path in sorted(self.cache_dir.glob(f"yfinance_provisional_{as_of_date}_*.csv"), key=lambda item: item.stat().st_mtime):
            try:
                for record in records_from_dataframe(pd.read_csv(path)):
                    if record.ticker in wanted:
                        cached[record.ticker] = record
            except Exception as exc:
                warnings.append(f"Skipped unreadable yfinance provisional partial cache {path}: {type(exc).__name__}: {exc}")
        if cached:
            warnings.append(f"Loaded {len(cached)} ticker rows from same-date yfinance provisional partial cache.")
        return cached

    def _write_cached_records(
        self,
        as_of_date: str,
        base_records: list[SecurityMasterRecord],
        records: list[SecurityMasterRecord],
        warnings: list[str],
    ) -> None:
        if not self.use_cache:
            return
        path = self._cache_path(as_of_date, base_records)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            records_to_dataframe(records).to_csv(path, index=False)
        except Exception as exc:
            warnings.append(f"Failed to write yfinance provisional cache {path}: {type(exc).__name__}: {exc}")

    def _cache_path(self, as_of_date: str, base_records: list[SecurityMasterRecord]) -> Path:
        tickers = "|".join(sorted(record.ticker for record in base_records))
        digest = hashlib.sha1(f"{as_of_date}|{tickers}".encode("utf-8")).hexdigest()[:12]
        return self.cache_dir / f"yfinance_provisional_{as_of_date}_{len(base_records)}_{digest}.csv"

    def _status_from_enrichment(self, records: list[SecurityMasterRecord], price_failures: list[str]) -> str:
        price_count = sum(record.price is not None for record in records)
        if price_count == 0:
            return "NO_USABLE_YFINANCE_PRICE_VOLUME"
        if price_failures:
            return "PARTIAL_YFINANCE_PUBLIC_FALLBACK_PROVISIONAL"
        return "LOADED_YFINANCE_PUBLIC_FALLBACK_PROVISIONAL"

    def _field_warning_counts(self, records: list[SecurityMasterRecord]) -> dict[str, int]:
        return {
            "missing_price": sum(record.price is None for record in records),
            "missing_adv_20d": sum(record.adv_20d is None for record in records),
            "missing_adv_60d": sum(record.adv_60d is None for record in records),
            "missing_market_cap": sum(record.market_cap is None for record in records),
            "missing_sector": sum(not record.sector for record in records),
            "missing_industry": sum(not record.industry for record in records),
        }

    def _coverage_warnings(self, counts: dict[str, int], total: int) -> list[str]:
        warnings = []
        for field, count in counts.items():
            if count:
                warnings.append(f"{field}: {count} of {total} provisional yfinance records are missing this field.")
        return warnings

    def _coverage(self, records: list[SecurityMasterRecord]) -> dict[str, Any]:
        total = len(records)
        counts = self._field_warning_counts(records)
        return {
            "total_records": total,
            "price_coverage": _coverage_ratio(total, total - counts["missing_price"]),
            "adv_20d_coverage": _coverage_ratio(total, total - counts["missing_adv_20d"]),
            "adv_60d_coverage": _coverage_ratio(total, total - counts["missing_adv_60d"]),
            "market_cap_coverage": _coverage_ratio(total, total - counts["missing_market_cap"]),
            "sector_coverage": _coverage_ratio(total, total - counts["missing_sector"]),
            "industry_coverage": _coverage_ratio(total, total - counts["missing_industry"]),
        }

    def _write_diagnostics(self, response: ProviderResponse, as_of_date: str, generated_at: str) -> None:
        payload = {
            "schema_version": "yfinance_provisional_diagnostics_v1",
            "generated_at": generated_at,
            "as_of_date": as_of_date,
            "data_source": DATA_SOURCE,
            "point_in_time_status": POINT_IN_TIME_STATUS,
            "research_use": RESEARCH_USE,
            "not_survivor_bias_free": NOT_SURVIVOR_BIAS_FREE,
            "status": response.status,
            "record_count": len(response.records),
            "warnings": response.warnings,
            "metadata": response.metadata,
        }
        try:
            self.diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
            self.diagnostics_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _to_yfinance_symbol(ticker: str) -> str:
    return normalize_ticker(ticker).replace(".", "-")


def _extract_ticker_frame(data: Any, yf_symbol: str) -> pd.DataFrame:
    if data is None:
        return pd.DataFrame()
    if not isinstance(data, pd.DataFrame) or data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        level0 = set(str(value) for value in data.columns.get_level_values(0))
        level1 = set(str(value) for value in data.columns.get_level_values(1))
        if yf_symbol in level0:
            return data[yf_symbol].copy()
        if yf_symbol in level1:
            return data.xs(yf_symbol, axis=1, level=1).copy()
        return pd.DataFrame()
    return data.copy()


def _price_volume_from_frame(frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty or "Close" not in frame.columns:
        return None
    close = pd.to_numeric(frame["Close"], errors="coerce")
    valid_close = close.dropna()
    if valid_close.empty:
        return None
    latest_date = pd.Timestamp(valid_close.index[-1]).date().isoformat()
    latest_price = float(valid_close.iloc[-1])
    if "Volume" in frame.columns:
        volume = pd.to_numeric(frame["Volume"], errors="coerce")
        dollar_volume = (close * volume).dropna()
        dollar_volume = dollar_volume.loc[dollar_volume > 0]
    else:
        dollar_volume = pd.Series(dtype="float64")
    return {
        "price": latest_price,
        "adv_20d": _mean_tail(dollar_volume, 20),
        "adv_60d": _mean_tail(dollar_volume, 60),
        "latest_date": latest_date,
        "price_observation_count": int(valid_close.count()),
        "dollar_volume_observation_count": int(dollar_volume.count()),
    }


def _mean_tail(series: pd.Series, window: int) -> float | None:
    if series.empty:
        return None
    return float(series.tail(window).mean())


def _safe_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        return dict(value)
    except Exception:
        return {}


def _first_float(*mappings: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for mapping in mappings:
        for key in keys:
            value = mapping.get(key)
            number = _try_float(value)
            if number is not None:
                return number
    return None


def _first_text(mapping: dict[str, Any], *, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _try_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coverage_ratio(total: int, covered: int) -> dict[str, float | int]:
    return {
        "covered": int(covered),
        "total": int(total),
        "ratio": float(covered / total) if total else 0.0,
    }
