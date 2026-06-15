"""Daily OHLCV download utilities for WorldQuant Alpha #2 research."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

import numpy as np
import pandas as pd
import yfinance as yf

DEFAULT_SOURCE = "yfinance"
DEFAULT_BATCH_SIZE = 50
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = (1.0, 2.0, 4.0)

OHLCV_LONG_COLUMNS = [
    "date",
    "ticker",
    "provider_symbol",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "source",
]

SYMBOL_MAP_COLUMNS = [
    "ticker",
    "provider_symbol",
    "mapping_changed",
    "mapping_status",
    "mapping_reason",
]

FAILURE_COLUMNS = [
    "ticker",
    "provider_symbol",
    "batch_id",
    "attempts",
    "error_type",
    "error_message",
    "status",
    "row_count",
    "usable_observation_count",
    "missing_value_count",
    "missing_value_ratio",
]

# Full normalized OHLCV schema stored by the downloader.
REQUIRED_OHLCV_VALUE_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]

# Alpha #2 signal and default execution require these fields only.
# High/Low remain in the normalized schema but are not used in usability checks.
# Strict v1 policy: partial_data remains excluded from the backtest universe.
ALPHA2_CRITICAL_VALUE_COLUMNS = ["open", "close", "adj_close", "volume"]

DATA_QUALITY_COLUMNS = [
    "ticker",
    "provider_symbol",
    "status",
    "row_count",
    "usable_observation_count",
    "missing_value_count",
    "missing_value_ratio",
    "reason",
    "batch_id",
    "attempts",
    "error_type",
]

# Matches Alpha #2 warmup: delta(2) + correlation(6) -> first finite alpha at row index 7.
DEFAULT_MIN_ALPHA2_OBSERVATIONS = 8
DEFAULT_DELTA_PERIODS = 2
DEFAULT_CORRELATION_WINDOW = 6

TICKER_STATUS_SUCCESS = "success"
TICKER_STATUS_PARTIAL_DATA = "partial_data"
TICKER_STATUS_INSUFFICIENT_HISTORY = "insufficient_history"
TICKER_STATUS_ALL_NAN = "all_nan"
TICKER_STATUS_MISSING_COLUMNS = "missing_columns"
TICKER_STATUS_EMPTY = "empty"
TICKER_STATUS_DUPLICATE_DATES = "duplicate_dates"
TICKER_STATUS_DOWNLOAD_ERROR = "download_error"

_CLASS_SHARE_DOT_PATTERN = re.compile(r"^[A-Z0-9]+\.[A-Z0-9]+$")
_ALLOWED_TICKER_PATTERN = re.compile(r"^[A-Z0-9.\-]+$")

DownloadFn = Callable[..., pd.DataFrame]


@dataclass(frozen=True)
class TickerMapping:
    ticker: str
    provider_symbol: str
    mapping_changed: bool
    mapping_status: str
    mapping_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "provider_symbol": self.provider_symbol,
            "mapping_changed": self.mapping_changed,
            "mapping_status": self.mapping_status,
            "mapping_reason": self.mapping_reason,
        }


def map_ticker_to_provider(ticker: str) -> TickerMapping:
    """Map a research ticker to the yfinance provider symbol."""
    normalized = str(ticker).strip().upper()
    if not normalized:
        return TickerMapping(
            ticker=str(ticker),
            provider_symbol="",
            mapping_changed=False,
            mapping_status="unsupported",
            mapping_reason="empty ticker after trim",
        )

    if not _ALLOWED_TICKER_PATTERN.fullmatch(normalized):
        return TickerMapping(
            ticker=normalized,
            provider_symbol="",
            mapping_changed=False,
            mapping_status="unsupported",
            mapping_reason="ticker contains unsupported characters",
        )

    if normalized.count(".") > 1:
        return TickerMapping(
            ticker=normalized,
            provider_symbol="",
            mapping_changed=False,
            mapping_status="unsupported",
            mapping_reason="multiple dot separators are ambiguous for yfinance mapping",
        )

    if "." in normalized:
        if _CLASS_SHARE_DOT_PATTERN.fullmatch(normalized):
            provider_symbol = normalized.replace(".", "-")
            return TickerMapping(
                ticker=normalized,
                provider_symbol=provider_symbol,
                mapping_changed=provider_symbol != normalized,
                mapping_status="dot_to_dash",
                mapping_reason="class-share dot format mapped to yfinance dash format",
            )
        return TickerMapping(
            ticker=normalized,
            provider_symbol="",
            mapping_changed=False,
            mapping_status="unsupported",
            mapping_reason="dot format is not a supported class-share pattern",
        )

    return TickerMapping(
        ticker=normalized,
        provider_symbol=normalized,
        mapping_changed=False,
        mapping_status="unchanged",
        mapping_reason="ordinary ticker passed through unchanged",
    )


def build_symbol_map(tickers: list[str]) -> pd.DataFrame:
    """Build a deterministic symbol map for the requested tickers."""
    ordered = sorted({str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()})
    rows = [map_ticker_to_provider(ticker).to_dict() for ticker in ordered]
    return pd.DataFrame(rows, columns=SYMBOL_MAP_COLUMNS)


def _clean_numeric(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    numeric = float(value)
    if not np.isfinite(numeric):
        return np.nan
    return numeric


def _extract_ticker_frame(raw: pd.DataFrame, provider_symbol: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        if provider_symbol not in raw.columns.get_level_values(0):
            return pd.DataFrame()
        frame = raw[provider_symbol].copy()
    else:
        frame = raw.copy()

    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(-1)
    return frame


def normalize_yfinance_history(
    raw: pd.DataFrame,
    *,
    ticker: str,
    provider_symbol: str,
    source: str = DEFAULT_SOURCE,
) -> pd.DataFrame:
    """Normalize one ticker's yfinance history into Alpha #2 long OHLCV format."""
    frame = _extract_ticker_frame(raw, provider_symbol)
    if frame.empty:
        return pd.DataFrame(columns=OHLCV_LONG_COLUMNS)

    output = frame.reset_index()
    date_column = "Date" if "Date" in output.columns else output.columns[0]
    rows: list[dict[str, Any]] = []
    for _, row in output.iterrows():
        rows.append(
            {
                "date": pd.to_datetime(row[date_column]).date().isoformat(),
                "ticker": ticker,
                "provider_symbol": provider_symbol,
                "open": _clean_numeric(row.get("Open")),
                "high": _clean_numeric(row.get("High")),
                "low": _clean_numeric(row.get("Low")),
                "close": _clean_numeric(row.get("Close")),
                "adj_close": _clean_numeric(row.get("Adj Close", row.get("Close"))),
                "volume": _clean_numeric(row.get("Volume")),
                "source": source,
            }
        )
    return pd.DataFrame(rows, columns=OHLCV_LONG_COLUMNS)


def validate_ohlcv_long_format(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and clean a long-format OHLCV panel."""
    if frame.empty:
        return frame.copy()

    missing = set(OHLCV_LONG_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"OHLCV frame is missing required columns: {sorted(missing)}")

    cleaned = frame.copy()
    cleaned["date"] = pd.to_datetime(cleaned["date"]).dt.date.astype(str)
    for column in ["open", "high", "low", "close", "adj_close", "volume"]:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
        cleaned[column] = cleaned[column].replace([np.inf, -np.inf], np.nan)

    duplicate_mask = cleaned.duplicated(subset=["ticker", "date"], keep=False)
    if duplicate_mask.any():
        duplicates = cleaned.loc[duplicate_mask, ["ticker", "date"]].drop_duplicates()
        raise ValueError(f"duplicate ticker-date rows found: {duplicates.to_dict('records')}")

    return cleaned.sort_values(["ticker", "date"]).reset_index(drop=True)


@dataclass(frozen=True)
class TickerDataQuality:
    ticker: str
    status: str
    row_count: int
    usable_observation_count: int
    missing_value_count: int
    missing_value_ratio: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "status": self.status,
            "row_count": self.row_count,
            "usable_observation_count": self.usable_observation_count,
            "missing_value_count": self.missing_value_count,
            "missing_value_ratio": self.missing_value_ratio,
            "reason": self.reason,
        }


def _alpha2_usable_row_mask(frame: pd.DataFrame) -> pd.Series:
    open_values = pd.to_numeric(frame["open"], errors="coerce")
    close_values = pd.to_numeric(frame["close"], errors="coerce")
    adj_close_values = pd.to_numeric(frame["adj_close"], errors="coerce")
    volume_values = pd.to_numeric(frame["volume"], errors="coerce")
    return (
        open_values.gt(0)
        & np.isfinite(open_values)
        & np.isfinite(close_values)
        & adj_close_values.gt(0)
        & np.isfinite(adj_close_values)
        & volume_values.gt(0)
        & np.isfinite(volume_values)
    )


def classify_ticker_ohlcv(
    frame: pd.DataFrame,
    *,
    ticker: str,
    min_valid_observations: int = DEFAULT_MIN_ALPHA2_OBSERVATIONS,
) -> TickerDataQuality:
    """Classify one ticker's long-format OHLCV history for Alpha #2 usability."""
    normalized_ticker = str(ticker).strip().upper()
    if frame.empty:
        return TickerDataQuality(
            ticker=normalized_ticker,
            status=TICKER_STATUS_EMPTY,
            row_count=0,
            usable_observation_count=0,
            missing_value_count=0,
            missing_value_ratio=1.0,
            reason="no rows returned for ticker",
        )

    missing_columns = set(ALPHA2_CRITICAL_VALUE_COLUMNS) - set(frame.columns)
    if missing_columns:
        return TickerDataQuality(
            ticker=normalized_ticker,
            status=TICKER_STATUS_MISSING_COLUMNS,
            row_count=int(len(frame)),
            usable_observation_count=0,
            missing_value_count=int(len(frame) * len(ALPHA2_CRITICAL_VALUE_COLUMNS)),
            missing_value_ratio=1.0,
            reason=f"missing Alpha #2 critical columns: {sorted(missing_columns)}",
        )

    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"]).dt.date.astype(str)
    duplicate_mask = working.duplicated(subset=["date"], keep=False)
    if duplicate_mask.any():
        duplicate_dates = sorted(working.loc[duplicate_mask, "date"].unique().tolist())
        return TickerDataQuality(
            ticker=normalized_ticker,
            status=TICKER_STATUS_DUPLICATE_DATES,
            row_count=int(len(working)),
            usable_observation_count=0,
            missing_value_count=0,
            missing_value_ratio=1.0,
            reason=f"duplicate dates found: {duplicate_dates}",
        )

    critical_frame = working[ALPHA2_CRITICAL_VALUE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    critical_frame = critical_frame.replace([np.inf, -np.inf], np.nan)
    total_cells = int(critical_frame.size)
    missing_value_count = int(critical_frame.isna().sum().sum())
    missing_value_ratio = float(missing_value_count / total_cells) if total_cells else 1.0

    has_price = critical_frame[["open", "close", "adj_close"]].notna().any(axis=1)
    if not has_price.any():
        return TickerDataQuality(
            ticker=normalized_ticker,
            status=TICKER_STATUS_ALL_NAN,
            row_count=int(len(working)),
            usable_observation_count=0,
            missing_value_count=missing_value_count,
            missing_value_ratio=missing_value_ratio,
            reason="all Alpha #2 critical values are NaN",
        )

    usable_mask = _alpha2_usable_row_mask(critical_frame)
    usable_observation_count = int(usable_mask.sum())
    if usable_observation_count == 0:
        return TickerDataQuality(
            ticker=normalized_ticker,
            status=TICKER_STATUS_ALL_NAN,
            row_count=int(len(working)),
            usable_observation_count=0,
            missing_value_count=missing_value_count,
            missing_value_ratio=missing_value_ratio,
            reason="no usable price/volume observations for Alpha #2",
        )

    if usable_observation_count < min_valid_observations:
        return TickerDataQuality(
            ticker=normalized_ticker,
            status=TICKER_STATUS_INSUFFICIENT_HISTORY,
            row_count=int(len(working)),
            usable_observation_count=usable_observation_count,
            missing_value_count=missing_value_count,
            missing_value_ratio=missing_value_ratio,
            reason=(
                f"only {usable_observation_count} usable observations; "
                f"need at least {min_valid_observations} for Alpha #2 rolling calculations"
            ),
        )

    if missing_value_ratio > 0.0:
        return TickerDataQuality(
            ticker=normalized_ticker,
            status=TICKER_STATUS_PARTIAL_DATA,
            row_count=int(len(working)),
            usable_observation_count=usable_observation_count,
            missing_value_count=missing_value_count,
            missing_value_ratio=missing_value_ratio,
            reason=(
                f"{usable_observation_count} usable observations with "
                f"{missing_value_ratio:.1%} missing Alpha #2 critical values"
            ),
        )

    return TickerDataQuality(
        ticker=normalized_ticker,
        status=TICKER_STATUS_SUCCESS,
        row_count=int(len(working)),
        usable_observation_count=usable_observation_count,
        missing_value_count=missing_value_count,
        missing_value_ratio=missing_value_ratio,
        reason="passed Alpha #2 market-data validation",
    )


def is_usable_ticker_status(status: str) -> bool:
    """Return True when a ticker may enter the Alpha #2 signal/backtest path."""
    return status == TICKER_STATUS_SUCCESS


def assess_ticker_data_quality(
    ohlcv: pd.DataFrame,
    requested_tickers: list[str],
    *,
    min_valid_observations: int = DEFAULT_MIN_ALPHA2_OBSERVATIONS,
) -> pd.DataFrame:
    """Build a per-ticker data-quality report for requested symbols."""
    requested = sorted({str(ticker).strip().upper() for ticker in requested_tickers if str(ticker).strip()})
    rows: list[dict[str, Any]] = []
    grouped = {}
    if not ohlcv.empty and "ticker" in ohlcv.columns:
        grouped = {str(ticker): group for ticker, group in ohlcv.groupby("ticker", sort=True)}

    for ticker in requested:
        frame = grouped.get(ticker, pd.DataFrame(columns=OHLCV_LONG_COLUMNS))
        assessment = classify_ticker_ohlcv(
            frame,
            ticker=ticker,
            min_valid_observations=min_valid_observations,
        )
        rows.append(
            {
                **assessment.to_dict(),
                "provider_symbol": frame["provider_symbol"].iloc[0]
                if not frame.empty and "provider_symbol" in frame.columns
                else "",
                "batch_id": pd.NA,
                "attempts": pd.NA,
                "error_type": pd.NA,
            }
        )
    return pd.DataFrame(rows, columns=DATA_QUALITY_COLUMNS)


def filter_usable_ohlcv(
    ohlcv: pd.DataFrame,
    quality_report: pd.DataFrame,
) -> pd.DataFrame:
    """Keep only tickers whose quality status is usable for Alpha #2."""
    if ohlcv.empty:
        return ohlcv.copy()
    usable = quality_report.loc[
        quality_report["status"].map(is_usable_ticker_status),
        "ticker",
    ].tolist()
    if not usable:
        return pd.DataFrame(columns=OHLCV_LONG_COLUMNS)
    return ohlcv.loc[ohlcv["ticker"].isin(usable)].reset_index(drop=True)


def _chunk_symbols(items: list[str], batch_size: int) -> list[list[str]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _default_download_fn(
    provider_symbols: list[str],
    *,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    return yf.download(
        tickers=provider_symbols,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=False,
    )


def _record_failure(
    failures: list[dict[str, Any]],
    *,
    ticker: str,
    provider_symbol: str,
    batch_id: int,
    attempts: int,
    error: Exception,
    status: str,
    quality: TickerDataQuality | None = None,
) -> None:
    record: dict[str, Any] = {
        "ticker": ticker,
        "provider_symbol": provider_symbol,
        "batch_id": batch_id,
        "attempts": attempts,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "status": status,
    }
    if quality is not None:
        record.update(
            {
                "row_count": quality.row_count,
                "usable_observation_count": quality.usable_observation_count,
                "missing_value_count": quality.missing_value_count,
                "missing_value_ratio": quality.missing_value_ratio,
            }
        )
    else:
        record.update(
            {
                "row_count": np.nan,
                "usable_observation_count": np.nan,
                "missing_value_count": np.nan,
                "missing_value_ratio": np.nan,
            }
        )
    failures.append(record)


def merge_download_failures_into_quality_report(
    quality_report: pd.DataFrame,
    download_failures: pd.DataFrame | None,
) -> pd.DataFrame:
    """Merge download-stage quality metrics into the final per-ticker report."""
    if download_failures is None or download_failures.empty:
        return quality_report

    merged = quality_report.copy()
    for column in DATA_QUALITY_COLUMNS:
        if column not in merged.columns:
            merged[column] = pd.NA

    numeric_fields = [
        "row_count",
        "usable_observation_count",
        "missing_value_count",
        "missing_value_ratio",
        "batch_id",
        "attempts",
    ]
    failure_lookup = download_failures.drop_duplicates(subset=["ticker"], keep="last").set_index("ticker")

    for idx, row in merged.iterrows():
        ticker = row["ticker"]
        if ticker not in failure_lookup.index:
            continue
        failure = failure_lookup.loc[ticker]
        merged.loc[idx, "status"] = failure.get("status", row["status"])
        merged.loc[idx, "reason"] = str(
            failure.get("error_message", failure.get("reason", row["reason"]))
        )
        if pd.notna(failure.get("provider_symbol", pd.NA)):
            merged.loc[idx, "provider_symbol"] = failure.get("provider_symbol")
        if pd.notna(failure.get("error_type", pd.NA)):
            merged.loc[idx, "error_type"] = failure.get("error_type")

        for field in numeric_fields:
            if field not in failure.index:
                merged.loc[idx, field] = pd.NA
                continue
            value = failure.get(field)
            if pd.notna(value):
                merged.loc[idx, field] = value
            else:
                merged.loc[idx, field] = pd.NA

    return merged[DATA_QUALITY_COLUMNS]


def download_ohlcv(
    tickers: list[str],
    *,
    start_date: str | date,
    end_date: str | date,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: tuple[float, ...] | list[float] = DEFAULT_BACKOFF_SECONDS,
    download_fn: DownloadFn | None = None,
    source: str = DEFAULT_SOURCE,
    include_rejected_history: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Download daily OHLCV for tickers with batching, retries, and partial success.

    When ``include_rejected_history`` is True, tickers classified as ``partial_data`` or
    ``insufficient_history`` are still retained in the returned OHLCV panel for dynamic
    multi-date validation, while failures are recorded separately.
    """
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")

    symbol_map = build_symbol_map(tickers)
    start = pd.to_datetime(start_date).date().isoformat()
    end = pd.to_datetime(end_date).date().isoformat()
    download = download_fn or _default_download_fn

    mappable = symbol_map.loc[
        symbol_map["mapping_status"] != "unsupported", ["ticker", "provider_symbol"]
    ].copy()
    unsupported = symbol_map.loc[symbol_map["mapping_status"] == "unsupported"].copy()

    ohlcv_parts: list[pd.DataFrame] = []
    failures: list[dict[str, Any]] = []

    for _, row in unsupported.iterrows():
        _record_failure(
            failures,
            ticker=row["ticker"],
            provider_symbol=row["provider_symbol"],
            batch_id=-1,
            attempts=0,
            error=ValueError(row["mapping_reason"]),
            status="mapping_failed",
        )

    provider_batches = _chunk_symbols(mappable["provider_symbol"].tolist(), batch_size)
    ticker_lookup = dict(zip(mappable["provider_symbol"], mappable["ticker"]))

    for batch_id, provider_batch in enumerate(provider_batches):
        raw: pd.DataFrame | None = None
        last_error: Exception | None = None
        attempts_used = 0
        for attempt in range(max_attempts):
            attempts_used = attempt + 1
            try:
                raw = download(provider_batch, start=start, end=end)
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 - structured failure capture
                last_error = exc
                if attempt < max_attempts - 1:
                    delay = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                    if delay:
                        time.sleep(delay)

        if last_error is not None or raw is None:
            for provider_symbol in provider_batch:
                _record_failure(
                    failures,
                    ticker=ticker_lookup[provider_symbol],
                    provider_symbol=provider_symbol,
                    batch_id=batch_id,
                    attempts=attempts_used,
                    error=last_error or RuntimeError("download returned no data"),
                    status="download_failed",
                )
            continue

        for provider_symbol in provider_batch:
            ticker = ticker_lookup[provider_symbol]
            normalized = normalize_yfinance_history(
                raw,
                ticker=ticker,
                provider_symbol=provider_symbol,
                source=source,
            )
            if normalized.empty:
                empty_quality = classify_ticker_ohlcv(normalized, ticker=ticker)
                _record_failure(
                    failures,
                    ticker=ticker,
                    provider_symbol=provider_symbol,
                    batch_id=batch_id,
                    attempts=attempts_used,
                    error=ValueError("provider returned no rows for ticker"),
                    status=TICKER_STATUS_EMPTY,
                    quality=empty_quality,
                )
                continue

            quality = classify_ticker_ohlcv(normalized, ticker=ticker)
            retain_for_validation = include_rejected_history and quality.status in {
                TICKER_STATUS_PARTIAL_DATA,
                TICKER_STATUS_INSUFFICIENT_HISTORY,
            }
            if not is_usable_ticker_status(quality.status):
                _record_failure(
                    failures,
                    ticker=ticker,
                    provider_symbol=provider_symbol,
                    batch_id=batch_id,
                    attempts=attempts_used,
                    error=ValueError(quality.reason),
                    status=quality.status,
                    quality=quality,
                )
                if retain_for_validation:
                    ohlcv_parts.append(normalized)
                continue
            ohlcv_parts.append(normalized)

    if ohlcv_parts:
        combined = validate_ohlcv_long_format(pd.concat(ohlcv_parts, ignore_index=True))
    else:
        combined = pd.DataFrame(columns=OHLCV_LONG_COLUMNS)

    failure_frame = pd.DataFrame(failures, columns=FAILURE_COLUMNS)
    return combined, failure_frame, symbol_map


def build_download_audit(
    requested_tickers: list[str],
    symbol_map: pd.DataFrame,
    ohlcv: pd.DataFrame,
    failures: pd.DataFrame,
    *,
    min_valid_observations: int = DEFAULT_MIN_ALPHA2_OBSERVATIONS,
) -> dict[str, Any]:
    """Summarize a download run for logging or smoke-test reporting."""
    requested = sorted({str(ticker).strip().upper() for ticker in requested_tickers if str(ticker).strip()})
    mapped = symbol_map.loc[symbol_map["mapping_status"] != "unsupported", "ticker"].tolist()
    downloaded_set = set(ohlcv["ticker"].unique().tolist()) if not ohlcv.empty else set()
    if not failures.empty and "row_count" in failures.columns:
        downloaded_set.update(
            failures.loc[
                pd.to_numeric(failures["row_count"], errors="coerce").fillna(0).gt(0),
                "ticker",
            ].astype(str)
        )
    downloaded = sorted(downloaded_set)
    failed = sorted(failures["ticker"].unique().tolist()) if not failures.empty else []
    quality_report = assess_ticker_data_quality(
        ohlcv,
        requested,
        min_valid_observations=min_valid_observations,
    )
    quality_report = merge_download_failures_into_quality_report(quality_report, failures)
    usable = sorted(
        quality_report.loc[quality_report["status"].map(is_usable_ticker_status), "ticker"].tolist()
    )
    rejected = sorted(
        quality_report.loc[~quality_report["status"].map(is_usable_ticker_status), "ticker"].tolist()
    )

    duplicate_count = 0
    if not ohlcv.empty:
        duplicate_count = int(ohlcv.duplicated(subset=["ticker", "date"]).sum())

    missing_counts = {}
    if not ohlcv.empty:
        for column in REQUIRED_OHLCV_VALUE_COLUMNS:
            missing_counts[column] = int(ohlcv[column].isna().sum())

    zero_volume_count = int((ohlcv["volume"].fillna(-1) == 0).sum()) if not ohlcv.empty else 0
    date_min = ohlcv["date"].min() if not ohlcv.empty else None
    date_max = ohlcv["date"].max() if not ohlcv.empty else None

    return {
        "requested_symbols": requested,
        "successfully_mapped": mapped,
        "successfully_downloaded": downloaded,
        "usable_symbols": usable,
        "rejected_symbols": rejected,
        "failed_symbols": failed,
        "quality_report": quality_report,
        "row_count": int(len(ohlcv)),
        "date_range": {"start": date_min, "end": date_max},
        "duplicate_ticker_date_count": duplicate_count,
        "missing_ohlcv_counts": missing_counts,
        "zero_volume_row_count": zero_volume_count,
    }


def format_download_audit(summary: dict[str, Any], *, output_paths: dict[str, str] | None = None) -> str:
    lines = [
        "WorldQuant Alpha #2 OHLCV download audit",
        f"  Requested symbols ({len(summary['requested_symbols'])}): {', '.join(summary['requested_symbols'])}",
        f"  Successfully mapped ({len(summary['successfully_mapped'])}): {', '.join(summary['successfully_mapped'])}",
        f"  Successfully downloaded ({len(summary['successfully_downloaded'])}): {', '.join(summary['successfully_downloaded'])}",
        f"  Usable symbols ({len(summary.get('usable_symbols', []))}): {', '.join(summary.get('usable_symbols', [])) or 'none'}",
        f"  Rejected symbols ({len(summary.get('rejected_symbols', []))}): {', '.join(summary.get('rejected_symbols', [])) or 'none'}",
        f"  Failed symbols ({len(summary['failed_symbols'])}): {', '.join(summary['failed_symbols']) or 'none'}",
        f"  Row count: {summary['row_count']}",
        f"  Date range: {summary['date_range']['start']} to {summary['date_range']['end']}",
        f"  Duplicate ticker-date count: {summary['duplicate_ticker_date_count']}",
        f"  Zero-volume row count: {summary['zero_volume_row_count']}",
    ]
    missing = summary.get("missing_ohlcv_counts") or {}
    if missing:
        lines.append("  Missing OHLCV counts:")
        for column, count in missing.items():
            lines.append(f"    - {column}: {count}")
    if output_paths:
        lines.append("  Output paths:")
        for name, path in output_paths.items():
            lines.append(f"    - {name}: {path}")
    return "\n".join(lines)
