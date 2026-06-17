"""Generate the cached delayed market-data proxy artifact for Risk Factors."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting.operational_snapshot import _build_market_proxy_cache_from_price_history


DEFAULT_CANONICAL_PATH = PROJECT_ROOT / "dashboard" / "data" / "canonical_operational.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "dashboard" / "data" / "risk_factor_market_proxy_cache.json"
BENCHMARK_SYMBOL = "SPY"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def yfinance_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def current_holding_universe(canonical: dict[str, Any]) -> list[dict[str, str]]:
    holdings = canonical.get("holdings") or []
    latest_date = max((row.get("date") or "" for row in holdings), default="")
    tickers = {
        str(row["ticker"])
        for row in holdings
        if row.get("date") == latest_date
        and row.get("ticker")
        and float(row.get("target_weight") or 0) != 0
    }
    return [
        {"ticker": ticker, "source_ticker": yfinance_symbol(ticker)}
        for ticker in sorted(tickers)
    ]


def normalize_yfinance_history(
    data: pd.DataFrame,
    universe: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    failed: list[str] = []
    source_to_ticker = {row["source_ticker"]: row["ticker"] for row in universe}
    source_to_ticker[BENCHMARK_SYMBOL] = BENCHMARK_SYMBOL
    multi = isinstance(data.columns, pd.MultiIndex)
    for source_ticker, ticker in source_to_ticker.items():
        if multi:
            if source_ticker not in data.columns.get_level_values(0):
                failed.append(ticker)
                continue
            frame = data[source_ticker].copy()
        else:
            frame = data.copy()
        if frame.empty or "Close" not in frame:
            failed.append(ticker)
            continue
        frame = frame.reset_index()
        usable = 0
        for _, source_row in frame.iterrows():
            close = source_row.get("Close")
            if pd.isna(close):
                continue
            date_value = source_row.get("Date") or source_row.get("Datetime")
            rows.append(
                {
                    "date": pd.to_datetime(date_value).date().isoformat(),
                    "ticker": ticker,
                    "source_ticker": source_ticker,
                    "open": _clean_float(source_row.get("Open")),
                    "high": _clean_float(source_row.get("High")),
                    "low": _clean_float(source_row.get("Low")),
                    "close": _clean_float(close),
                    "adj_close": _clean_float(source_row.get("Adj Close", close)),
                    "volume": _clean_float(source_row.get("Volume")),
                    "provider": "yfinance",
                }
            )
            usable += 1
        if usable == 0:
            failed.append(ticker)
    return rows, sorted(set(failed))


def fetch_yfinance_history(
    universe: list[dict[str, str]],
    *,
    period: str,
    interval: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    import yfinance as yf

    source_tickers = sorted({row["source_ticker"] for row in universe} | {BENCHMARK_SYMBOL})
    data = yf.download(
        tickers=source_tickers,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if data.empty:
        return [], [row["ticker"] for row in universe]
    return normalize_yfinance_history(data, universe)


def build_cache(
    canonical: dict[str, Any],
    *,
    fetch_history: Callable[[list[dict[str, str]]], tuple[list[dict[str, Any]], list[str]]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    universe = current_holding_universe(canonical)
    price_history, failed = fetch_history(universe)
    cache = _build_market_proxy_cache_from_price_history(
        price_history,
        generated_at=generated,
        provider="yfinance",
        requested_tickers=[row["ticker"] for row in universe],
        failed_tickers=failed,
    )
    metadata = cache.setdefault("metadata", {})
    loaded_tickers = {
        row.get("ticker")
        for row in cache.get("holdings_market_proxy") or []
        if row.get("status") == "LOADED"
    }
    requested = {row["ticker"] for row in universe}
    missing = sorted((requested - loaded_tickers) | set(failed))
    metadata.update(
        {
            "source": "committed_shadow_holdings",
            "benchmark_symbol": BENCHMARK_SYMBOL,
            "ticker_count_requested": len(requested),
            "ticker_count_successful": len(requested - set(missing)),
            "failed_tickers": missing,
            "warnings": [
                "Delayed yfinance market-data proxy cache.",
                "Not live real-time market data.",
                "Not a validated Barra / institutional factor model.",
                "Not VaR or Expected Shortfall.",
                "Not brokerage or live execution data.",
                "Sector metadata is included only when present in the cached source rows; missing sectors remain Not Available.",
            ],
        }
    )
    return cache


def write_cache(cache: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def _clean_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate delayed yfinance risk-factor market proxy cache.")
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--period", default="6mo")
    parser.add_argument("--interval", default="1d")
    args = parser.parse_args()

    canonical = load_json(args.canonical)

    def fetcher(universe: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
        return fetch_yfinance_history(universe, period=args.period, interval=args.interval)

    cache = build_cache(canonical, fetch_history=fetcher)
    write_cache(cache, args.output)
    metadata = cache.get("metadata") or {}
    benchmark = cache.get("benchmark") or {}
    print(
        json.dumps(
            {
                "output": str(args.output),
                "provider": metadata.get("provider"),
                "ticker_count_requested": metadata.get("ticker_count_requested"),
                "ticker_count_successful": metadata.get("ticker_count_successful"),
                "failed_ticker_count": len(metadata.get("failed_tickers") or []),
                "spy_return_count": benchmark.get("return_count"),
                "spy_status": benchmark.get("status"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
