"""yfinance market data fallback for the Risk Manager Platform."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


DEFAULT_UNIVERSE_PATH = Path("data/config/market_universe.json")
RAW_PRICE_PATH = Path("data/raw/yfinance_price_history.csv")
PROCESSED_PRICE_PATH = Path("data/processed/market_price_history.csv")
SNAPSHOT_PATH = Path("output/market_snapshot.json")


def load_market_universe(path: str | Path = DEFAULT_UNIVERSE_PATH) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload["tickers"])


def fetch_yfinance_prices(
    universe_path: str | Path = DEFAULT_UNIVERSE_PATH,
    years: int | None = None,
    raw_output_path: str | Path = RAW_PRICE_PATH,
    processed_output_path: str | Path = PROCESSED_PRICE_PATH,
) -> pd.DataFrame:
    universe = load_market_universe(universe_path)
    tickers = [row["ticker"] for row in universe]
    period = "max" if years is None else f"{years}y"
    data = yf.download(
        tickers=tickers,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if data.empty:
        raise ValueError("yfinance returned an empty price history")

    rows: list[dict[str, Any]] = []
    multi = isinstance(data.columns, pd.MultiIndex)
    for meta in universe:
        ticker = meta["ticker"]
        alias = meta.get("alias", ticker)
        if multi:
            if ticker not in data.columns.get_level_values(0):
                continue
            frame = data[ticker].copy()
        else:
            frame = data.copy()
        frame = frame.reset_index()
        for _, row in frame.iterrows():
            close = row.get("Close")
            if pd.isna(close):
                continue
            rows.append(
                {
                    "date": pd.to_datetime(row["Date"]).date().isoformat(),
                    "ticker": alias,
                    "source_ticker": ticker,
                    "name": meta.get("name", alias),
                    "bucket": meta.get("bucket", "other"),
                    "role": meta.get("role", ""),
                    "open": _clean_float(row.get("Open")),
                    "high": _clean_float(row.get("High")),
                    "low": _clean_float(row.get("Low")),
                    "close": _clean_float(close),
                    "adj_close": _clean_float(row.get("Adj Close", close)),
                    "volume": _clean_float(row.get("Volume")),
                    "source": "yfinance",
                }
            )
    panel = pd.DataFrame(rows)
    if panel.empty:
        raise ValueError("no usable yfinance rows after normalization")
    panel = panel.sort_values(["date", "ticker"]).reset_index(drop=True)
    Path(raw_output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(processed_output_path).parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(raw_output_path, index=False)
    panel.to_csv(processed_output_path, index=False)
    return panel


def build_market_snapshot(
    price_path: str | Path = PROCESSED_PRICE_PATH,
    output_path: str | Path = SNAPSHOT_PATH,
) -> dict[str, Any]:
    panel = pd.read_csv(price_path)
    if panel.empty:
        raise ValueError("price panel is empty")
    panel["date"] = pd.to_datetime(panel["date"])
    latest_date = panel["date"].max()
    previous_date = sorted(panel["date"].dropna().unique())[-2] if panel["date"].nunique() >= 2 else latest_date
    latest = panel[panel["date"] == latest_date].copy()
    previous = panel[panel["date"] == previous_date][["ticker", "close"]].rename(columns={"close": "previous_close"})
    merged = latest.merge(previous, on="ticker", how="left")
    merged["daily_return"] = merged["close"] / merged["previous_close"] - 1.0
    markets = []
    for _, row in merged.sort_values("ticker").iterrows():
        daily_return = _clean_float(row["daily_return"]) or 0.0
        markets.append(
            {
                "ticker": row["ticker"],
                "name": row.get("name", row["ticker"]),
                "bucket": row.get("bucket", "other"),
                "last": _clean_float(row["close"]),
                "daily_return": daily_return,
                "risk_interpretation": interpret_market_move(str(row["ticker"]), str(row.get("bucket", "")), daily_return),
            }
        )
    snapshot = {
        "as_of": latest_date.date().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "markets": markets,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return snapshot


def refresh_yfinance_market_data(years: int | None = None) -> dict[str, Any]:
    fetch_yfinance_prices(years=years)
    return build_market_snapshot()


def interpret_market_move(ticker: str, bucket: str, daily_return: float) -> str:
    direction = "up" if daily_return > 0 else "down"
    magnitude = abs(daily_return)
    if ticker == "VIX":
        return "Volatility stress rising" if daily_return > 0.03 else "Volatility pressure easing" if daily_return < -0.03 else "Volatility regime stable"
    if bucket == "rates_duration":
        return "Duration assets under pressure; rates may be rising" if daily_return < -0.005 else "Duration bid supports defensive sleeves" if daily_return > 0.005 else "Rates exposure stable"
    if bucket == "credit":
        return "Credit risk appetite supportive" if daily_return > 0 else "Credit sleeve under pressure; monitor spread widening"
    if bucket in {"equity_beta", "growth_equity", "small_cap", "style_factor"}:
        if magnitude > 0.015:
            return f"Equity/style proxy {direction}; review beta and factor concentration"
        return "Equity/style proxy stable"
    if bucket == "commodity":
        return "Commodity/inflation proxy firm" if daily_return > 0 else "Commodity/inflation proxy softer"
    if bucket == "usd_fx":
        return "USD pressure rising" if daily_return > 0 else "USD pressure easing"
    return "Market proxy updated from yfinance fallback"


def _clean_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
