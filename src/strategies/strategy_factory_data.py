"""Strategy Factory market data provider layer.

The Strategy Factory uses this module instead of binding directly to yfinance,
CSV files, or fixed artifact paths. V0 is prototype-only and intentionally
records data limitations rather than filling gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
import json
import os

import pandas as pd
import yaml


DATA_ROOT_ENV = "STRATEGY_FACTORY_DATA_ROOT"
DEFAULT_DATA_ROOT = Path(r"D:\Global_Ai\data\strategy_factory_market_data")
V0_SYMBOLS = [
    "CPER", "JJC", "DBB", "COPX", "XME",
    "SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "DBC", "UUP", "GLD", "USO",
    "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY",
]
DEFAULT_PROXY_MAPPING: dict[str, list[str]] = {
    "copper": ["CPER", "JJC", "DBB", "COPX"],
    "commodities_benchmark": ["DBC"],
    "equity_benchmark": ["SPY"],
    "usd_proxy": ["UUP"],
    "etf_rotation": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"],
    "sector_etfs": ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"],
}
DEFAULT_UNIVERSES: dict[str, list[str]] = {
    "v0_strategy_factory_proxies": V0_SYMBOLS,
    "copper_proxies": ["CPER", "JJC", "DBB", "COPX", "XME"],
    "risk_proxies": ["SPY", "DBC", "UUP", "GLD", "USO", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"],
    "etf_momentum_rotation": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"],
    "us_stock_momentum_quality": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "JPM", "XOM", "UNH", "AVGO"],
    "us_stock_low_vol_defensive": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "JPM", "XOM", "UNH", "AVGO"],
}
DECISION_READY = "READY_TO_BACKTEST"
DECISION_PROXY_ONLY = "PROXY_ONLY"
DECISION_TEXT_ONLY = "TEXT_ONLY_RESEARCH_CARD"
DECISION_BLOCKED = "BLOCKED_NEEDS_DATA"


class MarketDataProvider(Protocol):
    provider_name: str

    def get_price_history(self, symbols: list[str], start: str | None = None, end: str | None = None) -> pd.DataFrame:
        ...

    def get_returns(self, symbols: list[str], start: str | None = None, end: str | None = None) -> pd.DataFrame:
        ...

    def get_benchmark(self, symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        ...

    def get_universe(self, name: str) -> list[str]:
        ...

    def check_availability(self, requirements: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class DataAvailability:
    decision: str
    required_symbols: list[str]
    available_symbols: list[str]
    missing_symbols: list[str]
    proxy_symbols: list[str]
    usable_symbols: list[str]
    benchmark_symbol: str | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "strategy_factory_data_availability_v0",
            "decision": self.decision,
            "required_symbols": self.required_symbols,
            "available_symbols": self.available_symbols,
            "missing_symbols": self.missing_symbols,
            "proxy_symbols": self.proxy_symbols,
            "usable_symbols": self.usable_symbols,
            "benchmark_symbol": self.benchmark_symbol,
            "reason": self.reason,
        }


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def data_root() -> Path:
    return Path(os.environ.get(DATA_ROOT_ENV, str(DEFAULT_DATA_ROOT)))


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _normalize_symbols(symbols: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    return list(dict.fromkeys(str(symbol).upper().strip() for symbol in (symbols or []) if str(symbol).strip()))


def _date_filter(frame: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if frame.empty:
        return frame
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    if start:
        data = data[data["date"] >= pd.to_datetime(start)]
    if end:
        data = data[data["date"] <= pd.to_datetime(end)]
    return data


def _standardize_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "adj_close", "volume"])
    data = frame.copy()
    data.columns = [str(col).strip().lower().replace(" ", "_") for col in data.columns]
    rename = {"ticker": "symbol", "timestamp": "date", "adjusted_close": "adj_close", "price": "close"}
    data = data.rename(columns={key: value for key, value in rename.items() if key in data.columns})
    if "symbol" not in data.columns:
        wide_candidates = [col for col in data.columns if col != "date"]
        if "date" in data.columns and wide_candidates:
            data = data.melt(id_vars=["date"], value_vars=wide_candidates, var_name="symbol", value_name="close")
    if "adj_close" not in data.columns and "close" in data.columns:
        data["adj_close"] = data["close"]
    for col in ("open", "high", "low", "close", "adj_close", "volume"):
        if col not in data.columns:
            data[col] = pd.NA
    required = [col for col in ["date", "symbol", "open", "high", "low", "close", "adj_close", "volume"] if col in data.columns]
    data = data[required].dropna(subset=["date", "symbol"])
    data["symbol"] = data["symbol"].astype(str).str.upper().str.strip()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    for col in ("open", "high", "low", "close", "adj_close", "volume"):
        data[col] = pd.to_numeric(data[col], errors="coerce")
    return data.sort_values(["symbol", "date"]).reset_index(drop=True)


def _returns_from_prices(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(columns=["date", "symbol", "return"])
    data = prices.sort_values(["symbol", "date"]).copy()
    price_col = "adj_close" if "adj_close" in data.columns else "close"
    data["return"] = data.groupby("symbol")[price_col].pct_change(fill_method=None)
    return data[["date", "symbol", "return"]].dropna(subset=["return"]).reset_index(drop=True)


def ensure_data_layout(root: Path | None = None) -> Path:
    base = root or data_root()
    for directory in ("security_master", "prices", "macro", "manifests", "configs"):
        (base / directory).mkdir(parents=True, exist_ok=True)
    files = {
        base / "security_master" / "current_us_equity_universe.csv": "symbol,name\n",
        base / "security_master" / "etf_proxy_universe.csv": "symbol,name,proxy_group\n",
        base / "security_master" / "commodity_proxy_universe.csv": "symbol,name,proxy_group\n",
    }
    for path, content in files.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    write_default_configs(base)
    for path, payload in (
        (base / "manifests" / "data_inventory.json", empty_inventory()),
        (base / "manifests" / "data_quality_report.json", empty_quality_report()),
        (base / "manifests" / "provider_status.json", provider_status_payload("LOCAL_EMPTY", [], V0_SYMBOLS, "No data refresh has populated local files.")),
    ):
        if not path.exists():
            _write_json(path, payload)
    return base


def write_default_configs(root: Path | None = None) -> None:
    base = root or data_root()
    (base / "configs").mkdir(parents=True, exist_ok=True)
    proxy_path = base / "configs" / "proxy_mapping.yaml"
    universe_path = base / "configs" / "universe_definitions.yaml"
    if not proxy_path.exists():
        proxy_path.write_text(yaml.safe_dump(DEFAULT_PROXY_MAPPING, sort_keys=False), encoding="utf-8")
    if not universe_path.exists():
        universe_path.write_text(yaml.safe_dump(DEFAULT_UNIVERSES, sort_keys=False), encoding="utf-8")


def load_proxy_mapping(root: Path | None = None) -> dict[str, list[str]]:
    base = root or data_root()
    path = base / "configs" / "proxy_mapping.yaml"
    if not path.exists():
        write_default_configs(base)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(key): _normalize_symbols(value) for key, value in loaded.items()}


def empty_inventory() -> dict[str, Any]:
    return {
        "schema_version": "strategy_factory_data_inventory_v0",
        "datasets": [],
        "prototype_only": True,
        "pit_clean": False,
        "survivorship_bias_free": False,
        "last_refreshed": None,
    }


def empty_quality_report() -> dict[str, Any]:
    return {
        "schema_version": "strategy_factory_data_quality_report_v0",
        "missing_symbols": V0_SYMBOLS,
        "missing_date_ranges": [],
        "duplicate_rows": 0,
        "null_price_counts": {},
        "return_coverage": {},
        "warnings": ["No local Strategy Factory market data loaded."],
        "generated_at": now_utc(),
    }


def provider_status_payload(provider: str, available: list[str], missing: list[str], message: str) -> dict[str, Any]:
    return {
        "schema_version": "strategy_factory_provider_status_v0",
        "provider_mode": provider,
        "prototype_only": True,
        "available_symbols": _normalize_symbols(available),
        "missing_symbols": _normalize_symbols(missing),
        "message": message,
        "last_checked": now_utc(),
    }


class _BaseLocalProvider:
    provider_name = "LOCAL"

    def __init__(self, root: Path | None = None) -> None:
        self.root = ensure_data_layout(root or data_root())

    def get_returns(self, symbols: list[str], start: str | None = None, end: str | None = None) -> pd.DataFrame:
        symbols = _normalize_symbols(symbols)
        returns_path = self.root / "prices" / "daily_returns.parquet"
        if returns_path.exists():
            try:
                returns = pd.read_parquet(returns_path)
                returns.columns = [str(col).lower() for col in returns.columns]
                returns = returns.rename(columns={"ticker": "symbol"})
                returns["symbol"] = returns["symbol"].astype(str).str.upper().str.strip()
                returns = _date_filter(returns, start, end)
                return returns[returns["symbol"].isin(symbols)].reset_index(drop=True)
            except Exception:
                pass
        return _returns_from_prices(self.get_price_history(symbols, start, end))

    def get_benchmark(self, symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        return self.get_price_history([symbol], start, end)

    def get_universe(self, name: str) -> list[str]:
        path = self.root / "configs" / "universe_definitions.yaml"
        if not path.exists():
            write_default_configs(self.root)
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return _normalize_symbols(loaded.get(name, []))

    def check_availability(self, requirements: dict[str, Any]) -> dict[str, Any]:
        symbols = _normalize_symbols(requirements.get("symbols"))
        start = requirements.get("start")
        end = requirements.get("end")
        prices = self.get_price_history(symbols, start, end)
        available = sorted(set(prices["symbol"].unique())) if not prices.empty else []
        missing = [symbol for symbol in symbols if symbol not in available]
        return {
            "provider": self.provider_name,
            "required_symbols": symbols,
            "available_symbols": available,
            "missing_symbols": missing,
            "start": start,
            "end": end,
            "rows": int(len(prices)),
        }


class LocalParquetDataProvider(_BaseLocalProvider):
    provider_name = "LOCAL_PARQUET"

    def get_price_history(self, symbols: list[str], start: str | None = None, end: str | None = None) -> pd.DataFrame:
        symbols = _normalize_symbols(symbols)
        path = self.root / "prices" / "daily_ohlcv.parquet"
        if not path.exists():
            return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "adj_close", "volume"])
        frame = _standardize_price_frame(pd.read_parquet(path))
        frame = _date_filter(frame, start, end)
        return frame[frame["symbol"].isin(symbols)].reset_index(drop=True)


class LocalCsvMarketDataProvider(_BaseLocalProvider):
    provider_name = "LOCAL_CSV"

    def _csv_paths(self) -> list[Path]:
        prices = self.root / "prices"
        preferred = [prices / "daily_ohlcv.csv", prices / "daily_prices.csv"]
        discovered = sorted(prices.glob("*.csv")) if prices.exists() else []
        return list(dict.fromkeys([path for path in preferred + discovered if path.exists()]))

    def get_price_history(self, symbols: list[str], start: str | None = None, end: str | None = None) -> pd.DataFrame:
        symbols = _normalize_symbols(symbols)
        frames = []
        for path in self._csv_paths():
            frames.append(_standardize_price_frame(pd.read_csv(path)))
        if not frames:
            return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "adj_close", "volume"])
        frame = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["date", "symbol"], keep="last")
        frame = _date_filter(frame, start, end)
        return frame[frame["symbol"].isin(symbols)].sort_values(["symbol", "date"]).reset_index(drop=True)


class PublicFallbackDataLoader:
    provider_name = "PUBLIC_YFINANCE_FALLBACK"

    def __init__(self, root: Path | None = None) -> None:
        self.root = ensure_data_layout(root or data_root())

    def refresh_proxies(self, symbols: list[str] | None = None, start: str = "2018-01-01", end: str | None = None) -> dict[str, Any]:
        symbols = _normalize_symbols(symbols or V0_SYMBOLS)
        try:
            import yfinance as yf
        except Exception as exc:
            status = provider_status_payload(self.provider_name, [], symbols, f"yfinance unavailable: {exc}")
            _write_json(self.root / "manifests" / "provider_status.json", status)
            return {"ok": False, "error": str(exc), "provider_status": status}
        try:
            raw = yf.download(symbols, start=start, end=end, group_by="ticker", auto_adjust=False, progress=False, threads=False)
        except Exception as exc:
            status = provider_status_payload(self.provider_name, [], symbols, f"download failed: {exc}")
            _write_json(self.root / "manifests" / "provider_status.json", status)
            return {"ok": False, "error": str(exc), "provider_status": status}
        frames = []
        for symbol in symbols:
            if isinstance(raw.columns, pd.MultiIndex):
                if symbol not in raw.columns.get_level_values(0):
                    continue
                data = raw[symbol].reset_index()
            else:
                data = raw.reset_index()
            data["symbol"] = symbol
            frames.append(data)
        prices = _standardize_price_frame(pd.concat(frames, ignore_index=True)) if frames else pd.DataFrame()
        prices = prices.dropna(subset=["close"], how="all")
        csv_path = self.root / "prices" / "daily_ohlcv.csv"
        prices.to_csv(csv_path, index=False)
        try:
            prices.to_parquet(self.root / "prices" / "daily_ohlcv.parquet", index=False)
            _returns_from_prices(prices).to_parquet(self.root / "prices" / "daily_returns.parquet", index=False)
        except Exception:
            pass
        available = sorted(set(prices["symbol"].unique())) if not prices.empty else []
        missing = [symbol for symbol in symbols if symbol not in available]
        write_inventory_and_quality(self.root, prices, self.provider_name, missing)
        status = provider_status_payload(self.provider_name, available, missing, "Refresh completed from public fallback; prototype-only.")
        _write_json(self.root / "manifests" / "provider_status.json", status)
        return {"ok": True, "rows": int(len(prices)), "symbols": available, "missing_symbols": missing, "provider_status": status}


class BossApiDataProvider(_BaseLocalProvider):
    provider_name = "BOSS_API_STUB"

    def get_price_history(self, symbols: list[str], start: str | None = None, end: str | None = None) -> pd.DataFrame:
        raise NotImplementedError("Boss/API provider is a stub for future replacement.")


def select_local_provider(root: Path | None = None) -> MarketDataProvider:
    base = ensure_data_layout(root or data_root())
    parquet_path = base / "prices" / "daily_ohlcv.parquet"
    if parquet_path.exists():
        try:
            if len(pd.read_parquet(parquet_path, columns=["symbol"])) > 0:
                return LocalParquetDataProvider(base)
        except Exception:
            pass
    if parquet_path.exists() and not (base / "prices" / "daily_ohlcv.csv").exists():
        return LocalParquetDataProvider(base)
    return LocalCsvMarketDataProvider(base)


def write_inventory_and_quality(root: Path, prices: pd.DataFrame, source: str, missing_symbols: list[str] | None = None) -> None:
    ensure_data_layout(root)
    symbols = sorted(set(prices["symbol"].unique())) if not prices.empty and "symbol" in prices.columns else []
    start = str(pd.to_datetime(prices["date"]).min().date()) if not prices.empty else None
    end = str(pd.to_datetime(prices["date"]).max().date()) if not prices.empty else None
    duplicate_rows = int(prices.duplicated(subset=["date", "symbol"]).sum()) if not prices.empty else 0
    null_counts = {
        col: int(prices[col].isna().sum())
        for col in ("open", "high", "low", "close", "adj_close", "volume")
        if col in prices.columns
    }
    returns = _returns_from_prices(prices)
    return_coverage = returns.groupby("symbol")["return"].count().astype(int).to_dict() if not returns.empty else {}
    inventory = {
        "schema_version": "strategy_factory_data_inventory_v0",
        "datasets": [
            {
                "dataset_name": "daily_ohlcv",
                "source": source,
                "symbols": symbols,
                "start_date": start,
                "end_date": end,
                "rows": int(len(prices)),
                "frequency": "daily",
                "prototype_only": True,
                "pit_clean": False,
                "survivorship_bias_free": False,
                "last_refreshed": now_utc(),
            }
        ],
        "prototype_only": True,
        "pit_clean": False,
        "survivorship_bias_free": False,
        "last_refreshed": now_utc(),
    }
    missing = missing_symbols if missing_symbols is not None else [symbol for symbol in V0_SYMBOLS if symbol not in symbols]
    quality = {
        "schema_version": "strategy_factory_data_quality_report_v0",
        "missing_symbols": _normalize_symbols(missing),
        "missing_date_ranges": [],
        "duplicate_rows": duplicate_rows,
        "null_price_counts": null_counts,
        "return_coverage": return_coverage,
        "warnings": [
            "Prototype-only public/local data; not point-in-time clean.",
            "Survivorship-bias-free historical membership has not been supplied.",
        ],
        "generated_at": now_utc(),
    }
    _write_json(root / "manifests" / "data_inventory.json", inventory)
    _write_json(root / "manifests" / "data_quality_report.json", quality)


def load_inventory(root: Path | None = None) -> dict[str, Any]:
    base = ensure_data_layout(root or data_root())
    return _read_json(base / "manifests" / "data_inventory.json", empty_inventory())


def data_status(root: Path | None = None) -> dict[str, Any]:
    base = ensure_data_layout(root or data_root())
    provider = select_local_provider(base)
    inventory = load_inventory(base)
    status = _read_json(base / "manifests" / "provider_status.json", provider_status_payload(provider.provider_name, [], V0_SYMBOLS, "Provider status missing."))
    datasets = inventory.get("datasets") or []
    symbols = sorted({symbol for dataset in datasets for symbol in dataset.get("symbols", [])})
    latest = max([dataset.get("end_date") for dataset in datasets if dataset.get("end_date")] or [None])
    return {
        "ok": True,
        "schema_version": "strategy_factory_data_status_v0",
        "provider_mode": provider.provider_name,
        "data_root": str(base),
        "symbols_available": symbols or status.get("available_symbols", []),
        "latest_date": latest,
        "missing_required_data": status.get("missing_symbols", []),
        "prototype_only": True,
        "pit_clean": False,
        "survivorship_bias_free": False,
        "provider_status": status,
    }


def infer_data_requirements(run_manifest: dict[str, Any], text: str) -> dict[str, Any]:
    lower = text.lower()
    etf_tokens = {"etf", "rotation", "momentum rotation", "top 2", "top 3", "spy", "qqq", "iwm", "efa", "eem", "tlt", "gld"}
    copper_tokens = {"copper", "cper", "jjc", "copx", "xme", "hg=f"}
    us_stock_tokens = {"u.s. stock", "us stock", "u.s. equity", "us equity", "equity universe", "cross-sectional", "cross sectional", "quality", "roe", "gross margin", "profitability"}
    us_low_vol_tokens = {"low vol", "low-vol", "low volatility", "lower volatility", "defensive", "realized volatility", "beta filter"}
    if "copper" in lower or "commodit" in lower:
        return {
            "schema_version": "strategy_factory_data_requirements_v0",
            "asset_class": "commodity_proxy",
            "theme": "commodity_proxy_trend",
            "symbols": [],
            "proxy_groups": ["copper"],
            "benchmark_groups": ["commodities_benchmark"],
            "benchmark_symbol": "DBC",
            "start": None,
            "end": None,
            "run_id": run_manifest.get("run_id"),
        }
    if (("etf" in lower or "rotation" in lower) and any(token in lower for token in etf_tokens)) and not any(token in lower for token in copper_tokens):
        return {
            "schema_version": "strategy_factory_data_requirements_v0",
            "asset_class": "etf_rotation",
            "theme": "etf_momentum_rotation",
            "symbols": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"],
            "proxy_groups": ["etf_rotation"],
            "benchmark_groups": ["equity_benchmark"],
            "benchmark_symbol": "SPY",
            "start": None,
            "end": None,
            "run_id": run_manifest.get("run_id"),
        }
    if any(token in lower for token in us_low_vol_tokens):
        return {
            "schema_version": "strategy_factory_data_requirements_v0",
            "asset_class": "us_equity",
            "theme": "us_stock_low_vol_defensive",
            "symbols": [],
            "proxy_groups": [],
            "benchmark_groups": ["equity_benchmark"],
            "benchmark_symbol": "SPY",
            "start": None,
            "end": None,
            "run_id": run_manifest.get("run_id"),
        }
    if any(token in lower for token in us_stock_tokens):
        return {
            "schema_version": "strategy_factory_data_requirements_v0",
            "asset_class": "us_equity",
            "theme": "us_stock_cross_sectional_momentum_quality",
            "symbols": [],
            "proxy_groups": [],
            "benchmark_groups": ["equity_benchmark"],
            "benchmark_symbol": "SPY",
            "start": None,
            "end": None,
            "run_id": run_manifest.get("run_id"),
        }
    return {
        "schema_version": "strategy_factory_data_requirements_v0",
        "asset_class": "unknown",
        "theme": "unknown_review_required",
        "symbols": [],
        "proxy_groups": [],
        "benchmark_groups": [],
        "benchmark_symbol": None,
        "start": None,
        "end": None,
        "run_id": run_manifest.get("run_id"),
    }


def evaluate_availability(provider: MarketDataProvider, requirements: dict[str, Any], proxy_mapping: dict[str, list[str]] | None = None) -> DataAvailability:
    mapping = proxy_mapping or load_proxy_mapping(getattr(provider, "root", data_root()))
    required = _normalize_symbols(requirements.get("symbols"))
    proxy_symbols = _normalize_symbols([
        symbol
        for group in requirements.get("proxy_groups", [])
        for symbol in mapping.get(str(group), [])
    ])
    benchmark_symbols = _normalize_symbols([
        symbol
        for group in requirements.get("benchmark_groups", [])
        for symbol in mapping.get(str(group), [])
    ])
    benchmark = str(requirements.get("benchmark_symbol") or (benchmark_symbols[0] if benchmark_symbols else "")).upper() or None
    candidates = _normalize_symbols(required + proxy_symbols + ([benchmark] if benchmark else []))
    check = provider.check_availability({"symbols": candidates, "start": requirements.get("start"), "end": requirements.get("end")})
    available = _normalize_symbols(check.get("available_symbols"))
    exact_available = [symbol for symbol in required if symbol in available]
    usable_proxies = [symbol for symbol in proxy_symbols if symbol in available]
    benchmark_available = benchmark in available if benchmark else True
    if required and set(required).issubset(set(available)) and benchmark_available:
        decision = DECISION_READY
        usable = required
        reason = "Required symbols and benchmark are available."
    elif usable_proxies and benchmark_available:
        decision = DECISION_PROXY_ONLY
        usable = usable_proxies
        reason = "Required symbols are unavailable, but mapped proxy data and benchmark are available."
    elif requirements.get("asset_class") == "unknown":
        decision = DECISION_TEXT_ONLY
        usable = []
        reason = "No recognized market-data requirement was inferred from the current run."
    else:
        decision = DECISION_BLOCKED
        usable = []
        reason = "No required or mapped proxy symbols are available with benchmark data."
    missing = [symbol for symbol in candidates if symbol not in available]
    return DataAvailability(
        decision=decision,
        required_symbols=required,
        available_symbols=available,
        missing_symbols=missing,
        proxy_symbols=proxy_symbols,
        usable_symbols=usable,
        benchmark_symbol=benchmark,
        reason=reason,
    )


def write_run_data_artifacts(run_dir: Path, requirements: dict[str, Any], availability: DataAvailability, mapping: dict[str, list[str]]) -> dict[str, str]:
    artifacts = {
        "data_requirements": str(run_dir / "data_requirements.json"),
        "data_availability": str(run_dir / "data_availability.json"),
        "proxy_mapping_used": str(run_dir / "proxy_mapping_used.json"),
        "testability_decision": str(run_dir / "testability_decision.json"),
    }
    _write_json(Path(artifacts["data_requirements"]), requirements)
    _write_json(Path(artifacts["data_availability"]), availability.as_dict())
    _write_json(Path(artifacts["proxy_mapping_used"]), {"schema_version": "strategy_factory_proxy_mapping_used_v0", "mapping": mapping})
    _write_json(
        Path(artifacts["testability_decision"]),
        {
            "schema_version": "strategy_factory_testability_decision_v0",
            "decision": availability.decision,
            "reason": availability.reason,
            "usable_symbols": availability.usable_symbols,
            "benchmark_symbol": availability.benchmark_symbol,
            "generated_at": now_utc(),
        },
    )
    return artifacts
