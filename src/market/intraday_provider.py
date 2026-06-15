"""Intraday yfinance provider adapter for research proxy bars."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from src.market.demo_hosting import is_demo_hosting
from src.market.intraday_config import load_intraday_config, stale_after_minutes_for
from src.strategies.worldquant.market_data import map_ticker_to_provider

logger = logging.getLogger(__name__)


def _is_rate_limit_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return "ratelimit" in name or "too many requests" in message or "rate limited" in message


def bar_duration_minutes(bar_interval: str) -> int:
    interval = str(bar_interval).strip().lower()
    if interval.endswith("m"):
        return int(interval[:-1])
    if interval.endswith("h"):
        return int(interval[:-1]) * 60
    raise ValueError(f"unsupported bar interval: {bar_interval}")


def is_bar_complete(observation_ts_et: datetime, bar_interval: str, now_et: datetime) -> bool:
    duration = bar_duration_minutes(bar_interval)
    bar_end = observation_ts_et + timedelta(minutes=duration)
    return now_et >= bar_end


def partition_completed_bars(
    rows: list[dict[str, Any]],
    *,
    bar_interval: str,
    now_et: datetime | None = None,
    target_timezone: str = "America/New_York",
    incomplete_bar_label: str = "incomplete_current_bar",
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str | None]:
    """Split rows into completed bars and the latest incomplete bar per ticker."""
    tz = ZoneInfo(target_timezone)
    now = now_et or datetime.now(tz=ZoneInfo("UTC")).astimezone(tz)
    completed: list[dict[str, Any]] = []
    incomplete_latest: dict[str, dict[str, Any]] = {}
    latest_completed_ts: str | None = None

    for row in rows:
        ts = datetime.fromisoformat(row["observation_ts_et"])
        enriched = dict(row)
        if is_bar_complete(ts, bar_interval, now):
            enriched["bar_completeness"] = "completed"
            completed.append(enriched)
            if latest_completed_ts is None or enriched["observation_ts_et"] > latest_completed_ts:
                latest_completed_ts = enriched["observation_ts_et"]
        else:
            enriched["bar_completeness"] = incomplete_bar_label
            ticker = row["source_ticker"]
            prior = incomplete_latest.get(ticker)
            if prior is None or enriched["observation_ts_et"] > prior["observation_ts_et"]:
                incomplete_latest[ticker] = enriched

    return completed, incomplete_latest, latest_completed_ts


def fetch_intraday_bars(
    tickers: list[str],
    *,
    bar_interval: str,
    timeout_seconds: int | None = None,
    retry_attempts: int | None = None,
    backoff_seconds: list[int] | None = None,
    target_timezone: str = "America/New_York",
    stale_after_minutes: int | None = None,
    refresh_interval_minutes: int | None = None,
) -> dict[str, Any]:
    """Fetch intraday proxy bars for the given tickers.

    Returns normalized rows plus provider metadata. Does not mutate snapshots.
    """
    cfg = load_intraday_config()
    timeout_seconds = int(timeout_seconds or cfg.get("request_timeout_seconds") or 20)
    retry_attempts = int(retry_attempts or cfg.get("retry_attempts") or 3)
    backoff_seconds = list(backoff_seconds or cfg.get("backoff_seconds") or [5, 15, 30])
    source_tickers = sorted({ticker for ticker in tickers if ticker})
    if not source_tickers:
        raise ValueError("no tickers requested for intraday fetch")
    source_by_provider = {
        mapping.provider_symbol: mapping.ticker
        for mapping in (map_ticker_to_provider(ticker) for ticker in source_tickers)
        if mapping.provider_symbol
    }
    unique = sorted(source_by_provider)

    last_error: Exception | None = None
    raw = pd.DataFrame()
    use_threads = not is_demo_hosting()
    for attempt in range(retry_attempts):
        try:
            raw = yf.download(
                tickers=unique,
                period="1d",
                interval=bar_interval,
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                threads=use_threads,
                timeout=timeout_seconds,
            )
            if raw.empty:
                raise ValueError("yfinance returned empty intraday panel")
            break
        except Exception as exc:  # pragma: no cover - retried in tests via monkeypatch
            last_error = exc
            if _is_rate_limit_error(exc):
                logger.warning("yfinance rate limited during intraday fetch; shared demo hosts may need manual retry")
            if attempt + 1 >= retry_attempts:
                if last_error and _is_rate_limit_error(last_error):
                    raise ValueError(
                        "yfinance rate limited on shared demo host; using validated baseline artifact"
                    ) from last_error
                raise
            time.sleep(backoff_seconds[min(attempt, len(backoff_seconds) - 1)])
    if raw.empty:
        raise ValueError(str(last_error or "intraday fetch failed"))

    incomplete_label = cfg.get("incomplete_bar_label") or "incomplete_current_bar"
    stale_minutes = int(
        stale_after_minutes
        if stale_after_minutes is not None
        else stale_after_minutes_for(cfg, refresh_interval_minutes)
    )

    rows, missing, stale = _normalize_intraday_panel(
        raw,
        unique,
        bar_interval=bar_interval,
        target_timezone=target_timezone,
        stale_after_minutes=stale_minutes,
    )
    for row in rows:
        row["source_ticker"] = source_by_provider.get(row["source_ticker"], row["source_ticker"])
    missing = [source_by_provider.get(ticker, ticker) for ticker in missing]
    stale = [source_by_provider.get(ticker, ticker) for ticker in stale]
    tz = ZoneInfo(target_timezone)
    now_et = datetime.now(tz=ZoneInfo("UTC")).astimezone(tz)
    completed_rows, incomplete_latest, latest_completed_ts = partition_completed_bars(
        rows,
        bar_interval=bar_interval,
        now_et=now_et,
        target_timezone=target_timezone,
        incomplete_bar_label=incomplete_label,
    )
    valuation_rows = completed_rows if completed_rows else rows
    latest_ts = latest_completed_ts or max((row["observation_ts_et"] for row in valuation_rows), default=None)
    return {
        "provider": "yfinance",
        "bar_interval": bar_interval,
        "requested_tickers": source_tickers,
        "rows": valuation_rows,
        "all_rows": rows,
        "completed_rows": completed_rows,
        "incomplete_current_bars": list(incomplete_latest.values()),
        "missing_tickers": missing,
        "stale_tickers": stale,
        "ticker_count_requested": len(source_tickers),
        "ticker_count_successful": len({row["source_ticker"] for row in valuation_rows}),
        "latest_observation_ts_et": latest_ts,
        "latest_completed_bar_ts_et": latest_completed_ts,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "incomplete_bar_label": incomplete_label,
        "used_completed_bars_only": bool(completed_rows),
    }


def _normalize_intraday_panel(
    data: pd.DataFrame,
    tickers: list[str],
    *,
    bar_interval: str,
    target_timezone: str,
    stale_after_minutes: int,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    tz = ZoneInfo(target_timezone)
    now_et = datetime.now(tz=ZoneInfo("UTC")).astimezone(tz)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    multi = isinstance(data.columns, pd.MultiIndex)
    successful: set[str] = set()

    for ticker in tickers:
        if multi:
            if ticker not in data.columns.get_level_values(0):
                continue
            frame = data[ticker].copy()
        else:
            frame = data.copy()
        frame = frame.reset_index()
        time_col = next((name for name in ("Datetime", "Date", "index") if name in frame.columns), frame.columns[0])
        for _, row in frame.iterrows():
            close = row.get("Close")
            if pd.isna(close):
                continue
            ts = pd.to_datetime(row[time_col])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            ts_et = ts.astimezone(tz)
            key = (ticker, ts_et.isoformat())
            if key in seen:
                continue
            seen.add(key)
            open_px = _float(row.get("Open"))
            close_px = _float(close)
            intraday_return = None
            if open_px and open_px != 0:
                intraday_return = close_px / open_px - 1.0
            rows.append(
                {
                    "source_ticker": ticker,
                    "observation_ts_et": ts_et.isoformat(),
                    "session_date": ts_et.date().isoformat(),
                    "open": open_px,
                    "high": _float(row.get("High")),
                    "low": _float(row.get("Low")),
                    "close": close_px,
                    "volume": _float(row.get("Volume")),
                    "bar_interval": bar_interval,
                    "intraday_return_from_open": intraday_return,
                    "timezone": target_timezone,
                }
            )
            successful.add(ticker)

    missing = [ticker for ticker in tickers if ticker not in successful]
    stale: list[str] = []
    if rows:
        latest_by_ticker: dict[str, datetime] = {}
        for row in rows:
            ticker = row["source_ticker"]
            ts = datetime.fromisoformat(row["observation_ts_et"])
            latest_by_ticker[ticker] = max(latest_by_ticker.get(ticker, ts), ts)
        for ticker, ts in latest_by_ticker.items():
            age_minutes = (now_et - ts).total_seconds() / 60.0
            if age_minutes > stale_after_minutes:
                stale.append(ticker)
    rows.sort(key=lambda item: (item["source_ticker"], item["observation_ts_et"]))
    return rows, missing, stale


def latest_bar_by_ticker(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = row["source_ticker"]
        if ticker not in latest or row["observation_ts_et"] > latest[ticker]["observation_ts_et"]:
            latest[ticker] = row
    return latest


def latest_completed_bar_by_ticker(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    completed = [row for row in rows if row.get("bar_completeness") == "completed"]
    source = completed if completed else rows
    return latest_bar_by_ticker(source)


def _float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
