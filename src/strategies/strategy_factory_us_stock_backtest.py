"""Minimal U.S. stock 12-1 momentum evidence runner for Strategy Factory.

The runner uses current-listed public fallback universe data when institutional
point-in-time inputs are unavailable. It labels those limitations explicitly and
only reports metrics computed from loaded price data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import csv
import json
import math
import os

import pandas as pd


FORBIDDEN_SYMBOLS = {"COPX", "XME", "CPER", "JJC", "DBB", "DBC", "UUP", "USO", "GLD", "SPY", "QQQ", "IWM", "EFA", "EEM", "TLT"}
ETF_LIKE = {"SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD", "USO", "DBC", "UUP", "IVV", "VOO", "MDY", "MTUM", "QUAL", "VLUE", "USMV"}
DEFAULT_COST_BPS_PER_SIDE = 5.0
MIN_HISTORY_ROWS = 252 + 21 + 5


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _standardize_prices(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "symbol", "adj_close", "close", "volume"])
    data = frame.copy()
    data.columns = [str(col).strip().lower().replace(" ", "_") for col in data.columns]
    data = data.rename(columns={"ticker": "symbol", "timestamp": "date", "adjusted_close": "adj_close", "price": "close"})
    if "symbol" not in data.columns and "date" in data.columns:
        value_cols = [col for col in data.columns if col != "date"]
        data = data.melt(id_vars=["date"], value_vars=value_cols, var_name="symbol", value_name="close")
    if "adj_close" not in data.columns and "close" in data.columns:
        data["adj_close"] = data["close"]
    if "close" not in data.columns and "adj_close" in data.columns:
        data["close"] = data["adj_close"]
    if "volume" not in data.columns:
        data["volume"] = pd.NA
    needed = [col for col in ("date", "symbol", "adj_close", "close", "volume") if col in data.columns]
    data = data[needed].dropna(subset=["date", "symbol"])
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    data["symbol"] = data["symbol"].astype(str).str.upper().str.strip()
    data["adj_close"] = pd.to_numeric(data["adj_close"], errors="coerce")
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data["volume"] = pd.to_numeric(data["volume"], errors="coerce")
    return data.dropna(subset=["adj_close"]).sort_values(["symbol", "date"]).reset_index(drop=True)


def _price_candidates(root: Path) -> list[Path]:
    env_value = os.environ.get("STRATEGY_FACTORY_DATA_ROOT")
    env_root = Path(env_value) if env_value else None
    env_paths = [
        env_root / "prices" / "daily_ohlcv.csv",
        env_root / "prices" / "daily_ohlcv.parquet",
    ] if env_root else []
    return [
        *env_paths,
        root / "data" / "raw" / "yfinance_price_history.csv",
        root / "data" / "processed" / "market_price_history.csv",
        Path(r"D:\Global_Ai\data\strategy_factory_market_data\prices\daily_ohlcv.csv"),
        Path(r"D:\Global_Ai\data\strategy_factory_market_data\prices\daily_ohlcv.parquet"),
    ]


def _load_universe(root: Path, limit: int = 30) -> dict[str, Any]:
    security_master = root / "data" / "universe" / "security_master.csv"
    if security_master.exists():
        frame = pd.read_csv(security_master)
        data = frame.copy()
        data["ticker"] = data["ticker"].astype(str).str.upper().str.strip()
        for col in ("is_active", "is_common_stock", "is_etf"):
            if col in data.columns:
                data[col] = data[col].astype(str).str.lower().isin({"true", "1", "yes"})
        mask = data["ticker"].str.match(r"^[A-Z]{1,5}$", na=False)
        if "is_active" in data.columns:
            mask &= data["is_active"]
        if "is_common_stock" in data.columns:
            mask &= data["is_common_stock"]
        if "is_etf" in data.columns:
            mask &= ~data["is_etf"]
        if "country" in data.columns:
            mask &= data["country"].astype(str).str.upper().eq("US")
        data = data[mask & ~data["ticker"].isin(FORBIDDEN_SYMBOLS | ETF_LIKE)].copy()
        if "market_cap" in data.columns:
            data["market_cap"] = pd.to_numeric(data["market_cap"], errors="coerce")
            data = data.sort_values(["market_cap", "ticker"], ascending=[False, True])
        else:
            data = data.sort_values("ticker")
        tickers = list(dict.fromkeys(data["ticker"].head(limit).tolist()))
        if tickers:
            return {
                "input_universe_path": str(security_master),
                "tickers": tickers,
                "universe_limitations": [
                    "PUBLIC_FALLBACK_PROTOTYPE",
                    "NOT_POINT_IN_TIME",
                    "NOT_SURVIVORSHIP_BIAS_FREE",
                    "Current-listed U.S. common-stock sample sorted by market cap.",
                ],
            }
    fallback = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "JPM", "XOM", "UNH", "AVGO"]
    return {
        "input_universe_path": "DETERMINISTIC_LARGE_CAP_FALLBACK_NO_SECURITY_MASTER",
        "tickers": fallback[:limit],
        "universe_limitations": [
            "PUBLIC_FALLBACK_PROTOTYPE",
            "NOT_POINT_IN_TIME",
            "NOT_SURVIVORSHIP_BIAS_FREE",
            "Security master unavailable; deterministic large-cap sample used.",
        ],
    }


def _load_local_prices(root: Path, symbols: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    wanted = set(symbols + ["SPY"])
    inspected = []
    for path in _price_candidates(root):
        inspected.append(str(path))
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
        except Exception:
            continue
        prices = _standardize_prices(frame)
        if prices.empty:
            continue
        prices = prices[prices["symbol"].isin(wanted)]
        counts = prices.groupby("symbol")["date"].nunique().to_dict() if not prices.empty else {}
        stock_count = sum(1 for symbol in symbols if counts.get(symbol, 0) >= MIN_HISTORY_ROWS)
        if stock_count >= 5 and counts.get("SPY", 0) >= MIN_HISTORY_ROWS:
            return prices, {"price_data_source": "LOCAL_PRICE_CACHE", "price_data_path": str(path), "inspected_paths": inspected}
    return pd.DataFrame(), {"price_data_source": "LOCAL_PRICE_CACHE_MISSING", "price_data_path": None, "inspected_paths": inspected}


def _fetch_yfinance_prices(symbols: list[str], cache_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    if os.environ.get("STRATEGY_FACTORY_DISABLE_YFINANCE_DOWNLOAD") == "1":
        return pd.DataFrame(), {"price_data_source": "YFINANCE_PUBLIC_FALLBACK_DISABLED", "reason": "STRATEGY_FACTORY_DISABLE_YFINANCE_DOWNLOAD=1"}
    try:
        import yfinance as yf
    except Exception as exc:
        return pd.DataFrame(), {"price_data_source": "YFINANCE_PUBLIC_FALLBACK_UNAVAILABLE", "reason": f"yfinance import failed: {exc}"}
    tickers = list(dict.fromkeys(symbols + ["SPY"]))
    try:
        downloaded = yf.download(tickers, period="8y", interval="1d", auto_adjust=False, progress=False, threads=True, group_by="ticker")
    except Exception as exc:
        return pd.DataFrame(), {"price_data_source": "YFINANCE_PUBLIC_FALLBACK_FAILED", "reason": str(exc)}
    rows: list[dict[str, Any]] = []
    if downloaded.empty:
        return pd.DataFrame(), {"price_data_source": "YFINANCE_PUBLIC_FALLBACK_FAILED", "reason": "download returned no rows"}
    for ticker in tickers:
        try:
            one = downloaded[ticker] if isinstance(downloaded.columns, pd.MultiIndex) else downloaded
        except Exception:
            continue
        if one.empty:
            continue
        adj_col = "Adj Close" if "Adj Close" in one.columns else "Close"
        for date, row in one.reset_index().iterrows():
            date_value = row.get("Date") or row.get("date")
            price = _finite(row.get(adj_col))
            close = _finite(row.get("Close"))
            if date_value is None or price is None:
                continue
            rows.append(
                {
                    "date": pd.to_datetime(date_value).date().isoformat(),
                    "symbol": ticker,
                    "adj_close": price,
                    "close": close if close is not None else price,
                    "volume": _finite(row.get("Volume")),
                }
            )
    prices = _standardize_prices(pd.DataFrame(rows))
    if not prices.empty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        prices.to_csv(cache_path, index=False)
    return prices, {
        "price_data_source": "PUBLIC_YFINANCE_FALLBACK",
        "price_data_path": str(cache_path) if cache_path.exists() else None,
        "universe_limitations": ["PUBLIC_FALLBACK_PROTOTYPE", "NOT_POINT_IN_TIME", "NOT_SURVIVORSHIP_BIAS_FREE"],
    }


def _metrics(daily: pd.DataFrame, benchmark_available: bool) -> dict[str, Any]:
    returns = pd.to_numeric(daily["net_return"], errors="coerce").dropna()
    if returns.empty:
        return {"status": "BLOCKED", "reason": "No computed daily returns."}
    equity = (1.0 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    vol = float(returns.std(ddof=0) * math.sqrt(252)) if len(returns) else None
    ann = float(equity.iloc[-1] ** (252.0 / len(returns)) - 1.0) if len(returns) else None
    sharpe = float((returns.mean() / returns.std(ddof=0)) * math.sqrt(252)) if len(returns) > 1 and returns.std(ddof=0) > 0 else None
    benchmark_return = "Missing Evidence"
    excess_return = "Missing Evidence"
    if benchmark_available and "benchmark_return" in daily:
        bench = pd.to_numeric(daily["benchmark_return"], errors="coerce").dropna()
        if not bench.empty:
            bench_equity = (1.0 + bench).cumprod()
            benchmark_return = float(bench_equity.iloc[-1] ** (252.0 / len(bench)) - 1.0)
            excess_return = float(ann - benchmark_return) if ann is not None else "Missing Evidence"
    turnover_summary = _turnover_summary(daily)
    return {
        "status": "COMPLETED",
        "annual_return": ann,
        "volatility": vol,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else None,
        "turnover": turnover_summary["annualized_turnover"],
        **turnover_summary,
        "benchmark_annual_return": benchmark_return,
        "excess_return": excess_return,
        "rows": int(len(daily)),
        "date_range": {"start": str(daily["date"].iloc[0]), "end": str(daily["date"].iloc[-1])},
        "cost_assumption_bps_per_side": DEFAULT_COST_BPS_PER_SIDE,
    }


def _turnover_summary(daily: pd.DataFrame) -> dict[str, Any]:
    if "turnover" not in daily.columns or daily.empty:
        return {
            "turnover_value": None,
            "turnover_unit": "MISSING_EVIDENCE",
            "turnover_frequency": "monthly_rebalance",
            "turnover_definition": "Missing turnover series; cannot compute annualized one-way turnover.",
            "average_rebalance_turnover": None,
            "annualized_turnover": None,
            "cumulative_turnover": None,
            "rebalance_frequency_per_year": None,
        }
    turnover = pd.to_numeric(daily["turnover"], errors="coerce").fillna(0.0)
    active = turnover[turnover > 0.0]
    years = len(daily) / 252.0 if len(daily) else None
    cumulative = float(turnover.sum())
    frequency = float(len(active) / years) if years and years > 0 else None
    average_rebalance = float(active.mean()) if len(active) else 0.0
    annualized = float(cumulative / years) if years and years > 0 else None
    return {
        "turnover_value": annualized,
        "turnover_unit": "ANNUALIZED_ONE_WAY_MULTIPLE",
        "turnover_frequency": "monthly_rebalance",
        "turnover_definition": "One-way turnover_t = 0.5 * sum(abs(w_t - w_t-1)); annualized_turnover = average_rebalance_turnover * rebalance_frequency_per_year.",
        "average_rebalance_turnover": average_rebalance,
        "annualized_turnover": annualized,
        "cumulative_turnover": cumulative,
        "rebalance_frequency_per_year": frequency,
    }


def run_us_stock_12_1_backtest(root: Path, variant: dict[str, Any], evaluation_dir: Path, *, universe_limit: int = 30) -> dict[str, Any]:
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    universe = _load_universe(root, universe_limit)
    symbols = [symbol for symbol in universe["tickers"] if symbol not in FORBIDDEN_SYMBOLS and symbol not in ETF_LIKE]
    cache_path = evaluation_dir / "phase3d_yfinance_price_cache.csv"
    prices, price_meta = _load_local_prices(root, symbols)
    if prices.empty:
        prices, yf_meta = _fetch_yfinance_prices(symbols, cache_path)
        price_meta = {**price_meta, **yf_meta}
    price_meta.setdefault("price_data_path", str(cache_path) if cache_path.exists() else None)
    price_meta.setdefault("price_data_source", "Missing Evidence")

    if prices.empty:
        reason = f"DATA_MISSING: no U.S. stock price data loaded. Inspected: {price_meta.get('inspected_paths', [])}; provider reason: {price_meta.get('reason', 'unavailable')}"
        return {"status": "BLOCKED", "reason": reason, "universe": universe, "price_meta": price_meta}

    available_counts = prices.groupby("symbol")["date"].nunique().to_dict()
    usable = [symbol for symbol in symbols if available_counts.get(symbol, 0) >= MIN_HISTORY_ROWS]
    insufficient = {symbol: int(available_counts.get(symbol, 0)) for symbol in symbols if symbol not in usable}
    if len(usable) < 5 or available_counts.get("SPY", 0) < MIN_HISTORY_ROWS:
        reason = f"DATA_MISSING: need >=5 U.S. stocks and SPY with at least {MIN_HISTORY_ROWS} rows; usable={len(usable)}, SPY_rows={available_counts.get('SPY', 0)}"
        return {"status": "BLOCKED", "reason": reason, "universe": universe, "price_meta": price_meta, "insufficient_history": insufficient}

    matrix = prices[prices["symbol"].isin(usable + ["SPY"])].pivot_table(index="date", columns="symbol", values="adj_close", aggfunc="last").sort_index()
    matrix.index = pd.to_datetime(matrix.index)
    matrix = matrix.dropna(subset=["SPY"])
    stock_matrix = matrix[usable].dropna(how="all")
    common_index = stock_matrix.index.intersection(matrix.index)
    matrix = matrix.loc[common_index]
    signal = matrix[usable].shift(21) / matrix[usable].shift(252) - 1.0
    returns = matrix[usable].pct_change(fill_method=None)
    benchmark_returns = matrix["SPY"].pct_change(fill_method=None)
    months = pd.Series(matrix.index.to_period("M"), index=matrix.index)
    rebalance = months.ne(months.shift(1))
    top_n = min(50, max(5, min(20, len(usable))))
    holdings_rows: list[dict[str, Any]] = []
    weights = pd.DataFrame(0.0, index=matrix.index, columns=usable)
    last_weights = pd.Series(0.0, index=usable)
    for date in matrix.index:
        if not bool(rebalance.loc[date]):
            weights.loc[date] = last_weights
            continue
        scores = signal.loc[date].dropna().sort_values(ascending=False)
        chosen = [symbol for symbol in scores.index.tolist() if symbol in usable][:top_n]
        next_weights = pd.Series(0.0, index=usable)
        if chosen:
            next_weights.loc[chosen] = 1.0 / len(chosen)
        weights.loc[date] = next_weights
        last_weights = next_weights
        holdings_rows.append(
            {
                "rebalance_date": date.date().isoformat(),
                "signal_date": (date - pd.tseries.offsets.BDay(1)).date().isoformat(),
                "holdings": json.dumps(chosen),
                "holding_count": len(chosen),
                "top_n": top_n,
            }
        )
    weights = weights.ffill().fillna(0.0)
    turnover = (0.5 * weights.diff().abs().sum(axis=1)).fillna(0.5 * weights.abs().sum(axis=1))
    gross = (returns * weights.shift(1).fillna(0.0)).sum(axis=1)
    cost_drag = turnover * (DEFAULT_COST_BPS_PER_SIDE / 10000.0)
    net = gross - cost_drag
    daily = pd.DataFrame(
        {
            "date": matrix.index.date.astype(str),
            "gross_return": gross,
            "transaction_cost": cost_drag,
            "cost_drag": cost_drag,
            "net_return": net,
            "turnover": turnover,
            "benchmark_return": benchmark_returns,
            "holding_count": (weights > 0).sum(axis=1),
        }
    ).dropna(subset=["net_return", "benchmark_return"])
    daily = daily.iloc[MIN_HISTORY_ROWS:].reset_index(drop=True)
    if daily.empty:
        reason = "DATA_MISSING: 12-1 momentum backtest generated no valid post-warmup return rows."
        return {"status": "BLOCKED", "reason": reason, "universe": universe, "price_meta": price_meta, "insufficient_history": insufficient}

    metrics = _metrics(daily, True)
    summary = {
        "schema_version": "strategy_factory_us_stock_backtest_summary_v1",
        "status": "COMPLETED",
        "variant_id": variant.get("variant_id"),
        "theme": variant.get("theme"),
        "strategy_name": variant.get("strategy_name"),
        "input_universe_path": universe["input_universe_path"],
        "tickers_used": usable,
        "universe_count": len(usable),
        "universe_limitations": universe["universe_limitations"],
        "price_data_source": price_meta.get("price_data_source"),
        "price_data_path": price_meta.get("price_data_path"),
        "start_date": str(pd.to_datetime(daily["date"]).min().date()),
        "end_date": str(pd.to_datetime(daily["date"]).max().date()),
        "date_count": int(len(daily)),
        "missing_data_summary": {"insufficient_history": insufficient, "available_row_counts": {symbol: int(available_counts.get(symbol, 0)) for symbol in usable + ["SPY"]}},
        "signal_definition": "12-1 momentum = price[t-21] / price[t-252] - 1; monthly rebalance; rank cross-sectionally; hold top basket equal-weight.",
        "benchmark": "SPY",
        "transaction_cost_assumption": f"{DEFAULT_COST_BPS_PER_SIDE} bps per one-way turnover",
        "turnover_definition": metrics.get("turnover_definition"),
        "average_rebalance_turnover": metrics.get("average_rebalance_turnover"),
        "annualized_turnover": metrics.get("annualized_turnover"),
        "rebalance_periods": len(holdings_rows),
        "holdings_per_rebalance": top_n,
        "data_quality_status": "PUBLIC_FALLBACK_PROTOTYPE_NOT_PIT_NOT_SURVIVORSHIP_BIAS_FREE",
        "metrics": metrics,
        "generated_at": now_utc(),
    }
    signal_definition = {
        "schema_version": "strategy_factory_signal_definition_v1",
        "variant_id": variant.get("variant_id"),
        "signal_name": "12-1 cross-sectional momentum",
        "formula": "price[t-21] / price[t-252] - 1",
        "lookback_trading_days": 252,
        "skip_recent_trading_days": 21,
        "rebalance_frequency": "monthly",
        "execution_assumption": "positions use prior rebalance signal; returns applied from next row via shifted weights",
        "lookahead_check": "signal uses shifted prices and portfolio return uses weights.shift(1)",
    }
    _write_json(evaluation_dir / "backtest_summary.json", summary)
    _write_json(evaluation_dir / "signal_definition.json", signal_definition)
    _write_csv(evaluation_dir / "holdings_by_rebalance.csv", holdings_rows, ["rebalance_date", "signal_date", "holdings", "holding_count", "top_n"])
    daily.to_csv(evaluation_dir / "performance_series.csv", index=False)
    return {
        "status": "COMPLETED",
        "summary": summary,
        "signal_definition": signal_definition,
        "daily": daily,
        "holdings_rows": holdings_rows,
        "metrics": metrics,
        "universe": universe,
        "price_meta": price_meta,
        "artifacts": {
            "backtest_summary": str(evaluation_dir / "backtest_summary.json"),
            "signal_definition": str(evaluation_dir / "signal_definition.json"),
            "holdings_by_rebalance": str(evaluation_dir / "holdings_by_rebalance.csv"),
            "performance_series": str(evaluation_dir / "performance_series.csv"),
        },
    }


def run_us_stock_low_vol_backtest(root: Path, variant: dict[str, Any], evaluation_dir: Path, *, universe_limit: int = 30) -> dict[str, Any]:
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    universe = _load_universe(root, universe_limit)
    symbols = [symbol for symbol in universe["tickers"] if symbol not in FORBIDDEN_SYMBOLS and symbol not in ETF_LIKE]
    cache_path = evaluation_dir / "low_vol_yfinance_price_cache.csv"
    prices, price_meta = _load_local_prices(root, symbols)
    if prices.empty:
        prices, yf_meta = _fetch_yfinance_prices(symbols, cache_path)
        price_meta = {**price_meta, **yf_meta}
    price_meta.setdefault("price_data_path", str(cache_path) if cache_path.exists() else None)
    price_meta.setdefault("price_data_source", "Missing Evidence")

    if prices.empty:
        reason = f"DATA_MISSING: no U.S. stock price data loaded. Inspected: {price_meta.get('inspected_paths', [])}; provider reason: {price_meta.get('reason', 'unavailable')}"
        return {"status": "BLOCKED", "reason": reason, "universe": universe, "price_meta": price_meta}

    lookback = 63 if "63D" in str(variant.get("variant_id", "")).upper() else 126
    min_rows = lookback + 21 + 5
    available_counts = prices.groupby("symbol")["date"].nunique().to_dict()
    usable = [symbol for symbol in symbols if available_counts.get(symbol, 0) >= min_rows]
    insufficient = {symbol: int(available_counts.get(symbol, 0)) for symbol in symbols if symbol not in usable}
    if len(usable) < 5 or available_counts.get("SPY", 0) < min_rows:
        reason = f"DATA_MISSING: need >=5 U.S. stocks and SPY with at least {min_rows} rows; usable={len(usable)}, SPY_rows={available_counts.get('SPY', 0)}"
        return {"status": "BLOCKED", "reason": reason, "universe": universe, "price_meta": price_meta, "insufficient_history": insufficient}

    matrix = prices[prices["symbol"].isin(usable + ["SPY"])].pivot_table(index="date", columns="symbol", values="adj_close", aggfunc="last").sort_index()
    matrix.index = pd.to_datetime(matrix.index)
    matrix = matrix.dropna(subset=["SPY"])
    stock_matrix = matrix[usable].dropna(how="all")
    common_index = stock_matrix.index.intersection(matrix.index)
    matrix = matrix.loc[common_index]
    returns = matrix[usable].pct_change(fill_method=None)
    benchmark_returns = matrix["SPY"].pct_change(fill_method=None)
    realized_vol = returns.shift(1).rolling(lookback, min_periods=lookback).std() * math.sqrt(252)
    defensive_score = -realized_vol
    if "BETA_FILTER" in str(variant.get("variant_id", "")).upper():
        cov = returns.shift(1).rolling(lookback, min_periods=lookback).cov(benchmark_returns.shift(1))
        var = benchmark_returns.shift(1).rolling(lookback, min_periods=lookback).var()
        beta = cov.div(var, axis=0)
        defensive_score = defensive_score.where(beta <= 1.0)
    months = pd.Series(matrix.index.to_period("M"), index=matrix.index)
    rebalance = months.ne(months.shift(1))
    top_n = min(20, max(5, len(usable)))
    holdings_rows: list[dict[str, Any]] = []
    weights = pd.DataFrame(0.0, index=matrix.index, columns=usable)
    last_weights = pd.Series(0.0, index=usable)
    for date in matrix.index:
        if not bool(rebalance.loc[date]):
            weights.loc[date] = last_weights
            continue
        scores = defensive_score.loc[date].dropna().sort_values(ascending=False)
        chosen = [symbol for symbol in scores.index.tolist() if symbol in usable][:top_n]
        next_weights = pd.Series(0.0, index=usable)
        if chosen:
            next_weights.loc[chosen] = 1.0 / len(chosen)
        weights.loc[date] = next_weights
        last_weights = next_weights
        holdings_rows.append(
            {
                "rebalance_date": date.date().isoformat(),
                "signal_date": (date - pd.tseries.offsets.BDay(1)).date().isoformat(),
                "holdings": json.dumps(chosen),
                "holding_count": len(chosen),
                "top_n": top_n,
            }
        )
    weights = weights.ffill().fillna(0.0)
    turnover = (0.5 * weights.diff().abs().sum(axis=1)).fillna(0.5 * weights.abs().sum(axis=1))
    gross = (returns * weights.shift(1).fillna(0.0)).sum(axis=1)
    cost_drag = turnover * (DEFAULT_COST_BPS_PER_SIDE / 10000.0)
    net = gross - cost_drag
    daily = pd.DataFrame(
        {
            "date": matrix.index.date.astype(str),
            "gross_return": gross,
            "transaction_cost": cost_drag,
            "cost_drag": cost_drag,
            "net_return": net,
            "turnover": turnover,
            "benchmark_return": benchmark_returns,
            "holding_count": (weights > 0).sum(axis=1),
        }
    ).dropna(subset=["net_return", "benchmark_return"])
    daily = daily.iloc[min_rows:].reset_index(drop=True)
    if daily.empty:
        reason = "DATA_MISSING: low-vol defensive backtest generated no valid post-warmup return rows."
        return {"status": "BLOCKED", "reason": reason, "universe": universe, "price_meta": price_meta, "insufficient_history": insufficient}

    metrics = _metrics(daily, True)
    summary = {
        "schema_version": "strategy_factory_us_stock_backtest_summary_v1",
        "status": "COMPLETED",
        "variant_id": variant.get("variant_id"),
        "theme": variant.get("theme"),
        "strategy_name": variant.get("strategy_name"),
        "input_universe_path": universe["input_universe_path"],
        "tickers_used": usable,
        "universe_count": len(usable),
        "universe_limitations": universe["universe_limitations"],
        "price_data_source": price_meta.get("price_data_source"),
        "price_data_path": price_meta.get("price_data_path"),
        "start_date": str(pd.to_datetime(daily["date"]).min().date()),
        "end_date": str(pd.to_datetime(daily["date"]).max().date()),
        "date_count": int(len(daily)),
        "missing_data_summary": {"insufficient_history": insufficient, "available_row_counts": {symbol: int(available_counts.get(symbol, 0)) for symbol in usable + ["SPY"]}},
        "signal_definition": f"Low-vol defensive score = negative {lookback}d realized volatility of shifted daily returns; monthly rebalance; hold top defensive basket equal-weight.",
        "benchmark": "SPY",
        "transaction_cost_assumption": f"{DEFAULT_COST_BPS_PER_SIDE} bps per one-way turnover",
        "turnover_definition": metrics.get("turnover_definition"),
        "average_rebalance_turnover": metrics.get("average_rebalance_turnover"),
        "annualized_turnover": metrics.get("annualized_turnover"),
        "rebalance_periods": len(holdings_rows),
        "holdings_per_rebalance": top_n,
        "data_quality_status": "PUBLIC_FALLBACK_PROTOTYPE_NOT_PIT_NOT_SURVIVORSHIP_BIAS_FREE",
        "metrics": metrics,
        "generated_at": now_utc(),
    }
    signal_definition = {
        "schema_version": "strategy_factory_signal_definition_v1",
        "variant_id": variant.get("variant_id"),
        "signal_name": "U.S. stock low-vol defensive rank",
        "formula": f"-rolling_std(daily_return[t-1], {lookback}) * sqrt(252)",
        "lookback_trading_days": lookback,
        "rebalance_frequency": "monthly",
        "execution_assumption": "positions use prior rebalance signal; returns applied from next row via shifted weights",
        "lookahead_check": "volatility uses returns.shift(1) and portfolio return uses weights.shift(1)",
    }
    _write_json(evaluation_dir / "backtest_summary.json", summary)
    _write_json(evaluation_dir / "signal_definition.json", signal_definition)
    _write_csv(evaluation_dir / "holdings_by_rebalance.csv", holdings_rows, ["rebalance_date", "signal_date", "holdings", "holding_count", "top_n"])
    daily.to_csv(evaluation_dir / "performance_series.csv", index=False)
    return {
        "status": "COMPLETED",
        "summary": summary,
        "signal_definition": signal_definition,
        "daily": daily,
        "holdings_rows": holdings_rows,
        "metrics": metrics,
        "universe": universe,
        "price_meta": price_meta,
        "artifacts": {
            "backtest_summary": str(evaluation_dir / "backtest_summary.json"),
            "signal_definition": str(evaluation_dir / "signal_definition.json"),
            "holdings_by_rebalance": str(evaluation_dir / "holdings_by_rebalance.csv"),
            "performance_series": str(evaluation_dir / "performance_series.csv"),
        },
    }
