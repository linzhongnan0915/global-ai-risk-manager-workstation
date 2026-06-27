"""Strategy Factory Gate 3A/3B variant evaluation.

This module evaluates frozen Gate 2 variant specifications with local prototype
data only. It writes research artifacts under each variant folder and does not
touch dashboard layout, deployment, live trading, paper ledgers, or ranking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import csv
import json
import math

import pandas as pd

from src.strategies.strategy_factory_data import data_root, select_local_provider
from src.strategies.strategy_factory_ml import run_current_run_ml_diagnostics
from src.strategies.strategy_factory_readiness import write_variant_readiness
from src.strategies.strategy_factory_us_stock_backtest import run_us_stock_12_1_backtest, run_us_stock_low_vol_backtest


VARIANT_ID = "COPPER_CPER_MOMENTUM_21_63_V1"
THEME_ETF_MOMENTUM_ROTATION = "etf_momentum_rotation"
THEME_US_STOCK_MOMENTUM_QUALITY = "us_stock_cross_sectional_momentum_quality"
THEME_US_STOCK_LOW_VOL_DEFENSIVE = "us_stock_low_vol_defensive"
THEME_UNKNOWN_REVIEW_REQUIRED = "unknown_review_required"
REQUIRED_EVALUATION_ARTIFACTS = [
    "variant_backtest_run.json",
    "variant_metrics.json",
    "variant_daily_returns.csv",
    "variant_equity_curve.csv",
    "variant_drawdown.csv",
    "variant_ml_diagnostics_run.json",
    "variant_robustness_run.json",
    "variant_evidence_report.md",
    "variant_decision.json",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _run_dir(root: Path, run_id: str) -> Path:
    return root / "output" / "strategy_factory" / "runs" / run_id


def _variant_dir(root: Path, run_id: str, variant_id: str) -> Path:
    return _run_dir(root, run_id) / "variants" / variant_id


def _evaluation_paths(evaluation_dir: Path) -> dict[str, str]:
    return {
        "backtest_run": str(evaluation_dir / "variant_backtest_run.json"),
        "metrics": str(evaluation_dir / "variant_metrics.json"),
        "daily_returns": str(evaluation_dir / "variant_daily_returns.csv"),
        "equity_curve": str(evaluation_dir / "variant_equity_curve.csv"),
        "drawdown": str(evaluation_dir / "variant_drawdown.csv"),
        "ml_diagnostics_run": str(evaluation_dir / "variant_ml_diagnostics_run.json"),
        "feature_importance_csv": str(evaluation_dir / "variant_feature_importance.csv"),
        "feature_importance_json": str(evaluation_dir / "variant_feature_importance.json"),
        "prediction_quality": str(evaluation_dir / "variant_prediction_quality.json"),
        "train_test_split": str(evaluation_dir / "variant_train_test_split.json"),
        "leakage_check": str(evaluation_dir / "variant_leakage_check.json"),
        "robustness_run": str(evaluation_dir / "variant_robustness_run.json"),
        "evidence_manifest": str(evaluation_dir / "variant_evidence_manifest.json"),
        "readiness_status": str(evaluation_dir / "variant_readiness_status.json"),
        "evidence_report": str(evaluation_dir / "variant_evidence_report.md"),
        "decision": str(evaluation_dir / "variant_decision.json"),
        "backtest_summary": str(evaluation_dir / "backtest_summary.json"),
        "signal_definition": str(evaluation_dir / "signal_definition.json"),
        "holdings_by_rebalance": str(evaluation_dir / "holdings_by_rebalance.csv"),
        "performance_series": str(evaluation_dir / "performance_series.csv"),
    }


def _empty_csv_artifacts(paths: dict[str, str]) -> None:
    _write_csv(Path(paths["daily_returns"]), ["date", "variant_id", "gross_return", "transaction_cost", "cost_drag", "net_return", "turnover", "benchmark_return", "position", "signal_date", "execution_date", "base_cost_bps_per_side"], [])
    _write_csv(Path(paths["equity_curve"]), ["date", "strategy_equity", "benchmark_equity"], [])
    _write_csv(Path(paths["drawdown"]), ["date", "drawdown"], [])


def _price_matrix(prices: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(columns=symbols)
    data = prices.copy()
    price_col = "adj_close" if "adj_close" in data.columns else "close"
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    data[price_col] = pd.to_numeric(data[price_col], errors="coerce")
    matrix = data.pivot_table(index="date", columns="symbol", values=price_col, aggfunc="last")
    return matrix.reindex(columns=symbols).dropna(how="all").sort_index()


def _monthly_rebalance_mask(index: pd.DatetimeIndex) -> pd.Series:
    months = pd.Series(index.to_period("M"), index=index)
    return months.ne(months.shift(1))


def _write_missing_ml(paths: dict[str, str], reason: str, variant: dict[str, Any]) -> dict[str, Any]:
    ml = {
        "schema_version": "strategy_factory_ml_diagnostics_run_v0",
        "status": "BLOCKED",
        "ml_evidence_status": "MISSING_EVIDENCE",
        "reason": reason,
        "variant_id": variant.get("variant_id"),
        "theme": variant.get("theme"),
        "model": None,
        "models": [],
        "prediction_quality": {},
        "direction_quality": {},
        "feature_importance_available": False,
        "generated_at": _now(),
        "artifacts": paths,
    }
    _write_json(Path(paths["ml_diagnostics_run"]), ml)
    _write_json(Path(paths["feature_importance_json"]), {"status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": reason, "feature_importance": []})
    _write_csv(Path(paths["feature_importance_csv"]), ["feature", "importance", "model", "status"], [])
    _write_json(Path(paths["prediction_quality"]), {"schema_version": "strategy_factory_prediction_quality_v0", "status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": reason, "metrics": {}})
    _write_json(Path(paths["train_test_split"]), {"schema_version": "strategy_factory_train_test_split_v0", "status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": reason, "split_method": "chronological_no_shuffle"})
    _write_json(Path(paths["leakage_check"]), {"schema_version": "strategy_factory_leakage_check_v0", "status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": reason})
    return ml


def _metric_summary(daily: pd.DataFrame, benchmark: str, cost_bps: float) -> dict[str, Any]:
    returns = daily["net_return"].astype(float)
    benchmark_returns = daily["benchmark_return"].astype(float)
    equity = (1.0 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    ann_return = float(equity.iloc[-1] ** (252.0 / len(returns)) - 1.0) if len(returns) else None
    vol = float(returns.std(ddof=0) * math.sqrt(252)) if len(returns) else None
    sharpe = float((returns.mean() / returns.std(ddof=0)) * math.sqrt(252)) if len(returns) > 1 and returns.std(ddof=0) > 0 else None
    benchmark_equity = (1.0 + benchmark_returns).cumprod()
    benchmark_ann_return = float(benchmark_equity.iloc[-1] ** (252.0 / len(benchmark_returns)) - 1.0) if len(benchmark_returns) else None
    return {
        "schema_version": "strategy_factory_variant_metrics_v1",
        "status": "COMPLETED",
        "annual_return": ann_return,
        "benchmark_annual_return": benchmark_ann_return,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else None,
        "volatility": vol,
        "win_rate": float((returns > 0).mean()) if len(returns) else None,
        "average_daily_return": float(returns.mean()) if len(returns) else None,
        "turnover": float(daily["turnover"].sum()) if "turnover" in daily.columns else None,
        "cost_drag": float(daily["cost_drag"].sum()) if "cost_drag" in daily.columns else None,
        "benchmark": benchmark,
        "rows": int(len(daily)),
        "date_range": {
            "start": str(pd.to_datetime(daily["date"]).min().date()) if len(daily) else None,
            "end": str(pd.to_datetime(daily["date"]).max().date()) if len(daily) else None,
        },
        "cost_assumption_bps_per_side": cost_bps,
        "prototype_proxy_only": True,
        "generated_at": _now(),
    }


def _momentum(data: pd.DataFrame, symbol: str, lookback: int) -> pd.Series:
    return data[symbol].shift(1) / data[symbol].shift(lookback + 1) - 1.0


def _momentum_ex_recent(data: pd.DataFrame, symbol: str, lookback: int, skip: int = 21) -> pd.Series:
    return data[symbol].shift(skip + 1) / data[symbol].shift(lookback + skip + 1) - 1.0


def _realized_vol(data: pd.DataFrame, symbol: str, lookback: int) -> pd.Series:
    return data[symbol].pct_change(fill_method=None).shift(1).rolling(lookback, min_periods=lookback).std() * math.sqrt(252)


def _required_symbols_for_variant(variant: dict[str, Any]) -> list[str]:
    symbols = [str(symbol).upper() for symbol in (variant.get("universe_or_proxy") or [])]
    benchmark = str(variant.get("benchmark") or "").upper()
    if benchmark:
        symbols.append(benchmark)
    for item in variant.get("data_requirements") or []:
        token = str(item).upper().strip()
        if token.isalpha() and 2 <= len(token) <= 5:
            symbols.append(token)
    return list(dict.fromkeys(symbols))


def _variant_signal(
    variant: dict[str, Any],
    data: pd.DataFrame,
    short_lookback: int,
    long_lookback: int,
) -> tuple[pd.Series, pd.Series, str]:
    variant_id = str(variant.get("variant_id") or "")
    universe = [str(symbol).upper() for symbol in (variant.get("universe_or_proxy") or [])]
    benchmark = str(variant.get("benchmark") or "").upper()
    if not universe or not benchmark:
        raise ValueError("Variant spec must include universe_or_proxy and benchmark.")
    if any(symbol not in data.columns for symbol in [*universe, benchmark]):
        missing = [symbol for symbol in [*universe, benchmark] if symbol not in data.columns]
        raise ValueError(f"Missing price columns for required symbols: {', '.join(missing)}")

    returns = data[universe].pct_change(fill_method=None).mean(axis=1)
    description = variant.get("signal_formula") or variant_id
    if variant_id == "COPPER_CPER_MOMENTUM_21_63_V1":
        raw_signal = ((_momentum(data, "CPER", short_lookback) > 0.0) & (_momentum(data, "CPER", long_lookback) > 0.0)).astype(float)
    elif variant_id == "COPPER_CPER_MOMENTUM_VOL_FILTER_V1":
        vol_21 = _realized_vol(data, "CPER", 21)
        vol_252 = _realized_vol(data, "CPER", 252)
        raw_signal = ((_momentum(data, "CPER", long_lookback) > 0.0) & (vol_21 < vol_252)).astype(float)
    elif variant_id == "COPPER_CPER_DBC_RELATIVE_STRENGTH_V1":
        raw_signal = ((_momentum(data, "CPER", long_lookback) - _momentum(data, "DBC", long_lookback)) > 0.0).astype(float)
    elif variant_id == "COPPER_CPER_UUP_USD_FILTER_V1":
        if "UUP" not in data.columns:
            raise ValueError("UUP is required for the USD-filter variant.")
        raw_signal = ((_momentum(data, "CPER", long_lookback) > 0.0) & (_momentum(data, "UUP", long_lookback) <= 0.0)).astype(float)
    elif variant_id == "COPPER_EQUITY_PROXY_TREND_COPX_XME_V1":
        raw_signal = (
            (_momentum(data, "COPX", long_lookback) > 0.0)
            & (_momentum(data, "XME", long_lookback) > 0.0)
            & ((_momentum(data, "COPX", long_lookback) - _momentum(data, "SPY", long_lookback)) > 0.0)
        ).astype(float)
    elif variant_id == "COMMODITY_BASKET_REGIME_FILTER_V1":
        regime_lookback = max(long_lookback, 126)
        raw_signal = ((_momentum(data, "CPER", long_lookback) > 0.0) & (_momentum(data, "DBC", regime_lookback) > 0.0)).astype(float)
    elif variant_id in {"ETF_ROTATION_63_126_TOP2_V1", "ETF_ROTATION_63_126_TOP3_V1"}:
        top_n = 2 if variant_id == "ETF_ROTATION_63_126_TOP2_V1" else 3
        score = pd.DataFrame(
            {
                symbol: _momentum(data, symbol, 63) + _momentum(data, symbol, 126)
                for symbol in universe
            },
            index=data.index,
        )
        ranks = score.rank(axis=1, ascending=False, method="first")
        raw_signal = (ranks <= top_n).astype(float).div(float(top_n))
        returns = (data[universe].pct_change(fill_method=None) * raw_signal.shift(1).fillna(0.0)).sum(axis=1)
    elif variant.get("theme") == THEME_US_STOCK_MOMENTUM_QUALITY:
        if "US_EQUITY_UNIVERSE" in universe:
            raise ValueError("DATA_MISSING: concrete U.S. stock tickers are required for cross-sectional momentum evidence.")
        lookback = 126 if "6_1" in variant_id else 252
        top_n = min(50, max(1, len(universe)))
        score = pd.DataFrame(
            {
                symbol: _momentum_ex_recent(data, symbol, lookback, 21)
                for symbol in universe
            },
            index=data.index,
        )
        ranks = score.rank(axis=1, ascending=False, method="first")
        raw_signal = (ranks <= top_n).astype(float).div(float(top_n))
        returns = (data[universe].pct_change(fill_method=None) * raw_signal.shift(1).fillna(0.0)).sum(axis=1)
    elif variant.get("theme") == THEME_US_STOCK_LOW_VOL_DEFENSIVE:
        if "US_EQUITY_UNIVERSE" in universe:
            raise ValueError("DATA_MISSING: concrete U.S. stock tickers are required for low-vol defensive evidence.")
        lookback = 63 if "63D" in variant_id else 126
        top_n = min(20, max(1, len(universe)))
        stock_returns = data[universe].pct_change(fill_method=None)
        score = -(stock_returns.shift(1).rolling(lookback, min_periods=lookback).std() * math.sqrt(252))
        ranks = score.rank(axis=1, ascending=False, method="first")
        raw_signal = (ranks <= top_n).astype(float).div(float(top_n))
        returns = (stock_returns * raw_signal.shift(1).fillna(0.0)).sum(axis=1)
    else:
        raise ValueError(f"Unsupported Gate 3B variant signal: {variant_id}")
    return raw_signal, returns, str(description)


def _run_variant_backtest(
    matrix: pd.DataFrame,
    variant: dict[str, Any],
    short_lookback: int = 21,
    long_lookback: int = 63,
    cost_bps: float = 5.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    variant_id = str(variant.get("variant_id"))
    benchmark = str(variant.get("benchmark") or "").upper()
    required = _required_symbols_for_variant(variant)
    data = matrix[required].dropna().copy()
    if variant.get("theme") == THEME_US_STOCK_MOMENTUM_QUALITY:
        min_required = (126 if "6_1" in variant_id else 252) + 26
    elif variant.get("theme") == THEME_US_STOCK_LOW_VOL_DEFENSIVE:
        min_required = (63 if "63D" in variant_id else 126) + 26
    else:
        min_required = max(long_lookback, 126 if variant_id == "COMMODITY_BASKET_REGIME_FILTER_V1" else long_lookback) + 5
    if len(data) <= min_required:
        raise ValueError(f"Only {len(data)} overlapping rows for {', '.join(required)}; need more than {min_required}.")
    raw_signal, asset_return, _ = _variant_signal(variant, data, short_lookback, long_lookback)
    benchmark_return = data[benchmark].pct_change(fill_method=None)
    rebalance = _monthly_rebalance_mask(data.index)
    if isinstance(raw_signal, pd.DataFrame):
        target = raw_signal.copy()
        target.loc[~rebalance, :] = pd.NA
        target = target.ffill().fillna(0.0)
        turnover = (0.5 * target.diff().abs().sum(axis=1)).fillna(0.5 * target.abs().sum(axis=1))
        position_output = target.astype(float).round(8).apply(lambda row: json.dumps({symbol: value for symbol, value in row.items() if value > 0.0}, sort_keys=True), axis=1)
    else:
        target = raw_signal.where(rebalance, other=pd.NA).ffill().fillna(0.0)
        turnover = target.diff().abs().fillna(target.abs())
        position_output = target
    cost_drag = turnover * (cost_bps / 10000.0)
    gross = asset_return if isinstance(target, pd.DataFrame) else target * asset_return
    net = gross - cost_drag
    daily = pd.DataFrame(
        {
            "date": data.index,
            "variant_id": variant_id,
            "gross_return": gross,
            "transaction_cost": cost_drag,
            "cost_drag": cost_drag,
            "net_return": net,
            "turnover": turnover,
            "benchmark_return": benchmark_return,
            "position": position_output,
            "signal_date": data.index - pd.tseries.offsets.BDay(1),
            "execution_date": data.index,
            "base_cost_bps_per_side": cost_bps,
        }
    ).dropna(subset=["gross_return", "net_return", "benchmark_return"])
    if daily.empty:
        raise ValueError("Variant backtest generated no valid return rows.")
    daily["date"] = daily["date"].dt.date.astype(str)
    daily["signal_date"] = pd.to_datetime(daily["signal_date"]).dt.date.astype(str)
    daily["execution_date"] = pd.to_datetime(daily["execution_date"]).dt.date.astype(str)
    equity = pd.DataFrame(
        {
            "date": daily["date"],
            "strategy_equity": (1.0 + daily["net_return"].astype(float)).cumprod(),
            "benchmark_equity": (1.0 + daily["benchmark_return"].astype(float)).cumprod(),
        }
    )
    drawdown = pd.DataFrame(
        {
            "date": daily["date"],
            "drawdown": equity["strategy_equity"] / equity["strategy_equity"].cummax() - 1.0,
        }
    )
    metrics = _metric_summary(daily, benchmark, cost_bps)
    metrics["lookbacks"] = {"short": short_lookback, "long": long_lookback}
    metrics["universe"] = [str(symbol).upper() for symbol in variant.get("universe_or_proxy") or []]
    metrics["theme"] = variant.get("theme")
    if variant.get("theme") == THEME_US_STOCK_MOMENTUM_QUALITY:
        metrics["quality_evidence_status"] = "MISSING_EVIDENCE"
        metrics["quality_evidence_reason"] = "Profitability, ROE, and gross-margin source fields were not supplied to this price-only evidence pass."
        metrics["input_universe"] = variant.get("universe_or_proxy") or []
    elif variant.get("theme") == THEME_US_STOCK_LOW_VOL_DEFENSIVE:
        metrics["strategy_evidence_family"] = "LOW_VOL_DEFENSIVE"
        metrics["feature_definition"] = "Lower 63d/126d realized volatility of shifted daily adjusted returns."
        metrics["input_universe"] = variant.get("universe_or_proxy") or []
    return daily, equity, drawdown, metrics


def _run_cper_momentum_backtest(
    matrix: pd.DataFrame,
    variant_id: str,
    asset: str,
    benchmark: str,
    short_lookback: int = 21,
    long_lookback: int = 63,
    cost_bps: float = 5.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    variant = {
        "variant_id": variant_id,
        "universe_or_proxy": [asset],
        "benchmark": benchmark,
        "data_requirements": [asset, benchmark],
    }
    return _run_variant_backtest(matrix, variant, short_lookback, long_lookback, cost_bps)


def _blocked_outputs(paths: dict[str, str], source_run_id: str, variant: dict[str, Any], reason: str) -> dict[str, Any]:
    _empty_csv_artifacts(paths)
    common = {
        "status": "BLOCKED",
        "reason": reason,
        "source_run_id": source_run_id,
        "variant_id": variant.get("variant_id"),
        "generated_at": _now(),
    }
    backtest = {
        "schema_version": "strategy_factory_variant_backtest_run_v1",
        **common,
        "local_data_only": True,
        "live_trading": "NOT_TOUCHED",
        "paper_ledger": "NOT_MUTATED",
    }
    metrics = {"schema_version": "strategy_factory_variant_metrics_v1", **common, "metrics": {}}
    ml = {
        "schema_version": "strategy_factory_ml_diagnostics_run_v0",
        **common,
        "ml_evidence_status": "MISSING_EVIDENCE",
        "models": [],
        "feature_importance_available": False,
    }
    robustness = {"schema_version": "strategy_factory_variant_robustness_run_v1", **common, "tests": []}
    decision = {
        "schema_version": "strategy_factory_variant_decision_v1",
        **common,
        "decision": "Blocked",
        "recommendation": "Blocked",
        "candidate": False,
    }
    _write_json(Path(paths["backtest_run"]), backtest)
    _write_json(Path(paths["metrics"]), metrics)
    _write_json(Path(paths["ml_diagnostics_run"]), ml)
    _write_json(Path(paths["robustness_run"]), robustness)
    _write_json(Path(paths["decision"]), decision)
    _write_evidence_report(Path(paths["evidence_report"]), variant, backtest, metrics, ml, robustness, decision)
    readiness = write_variant_readiness(Path(paths["evidence_report"]).parent, variant, backtest, metrics, ml, paths)
    decision.update(
        {
            "automation_ready": readiness["readiness"]["automation_ready"],
            "automation_block_reason": readiness["readiness"]["automation_block_reason"],
        }
    )
    _write_json(Path(paths["decision"]), decision)
    return {"status": "BLOCKED", "reason": reason, "artifacts": paths, "decision": decision}


def _metrics_for_series(returns: pd.Series) -> dict[str, Any]:
    returns = pd.to_numeric(returns, errors="coerce").dropna()
    if returns.empty:
        return {"status": "BLOCKED", "reason": "No returns available."}
    equity = (1.0 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    std = returns.std(ddof=0)
    return {
        "annual_return": float(equity.iloc[-1] ** (252.0 / len(returns)) - 1.0),
        "sharpe": float((returns.mean() / std) * math.sqrt(252)) if std > 0 else None,
        "max_drawdown": float(drawdown.min()),
        "volatility": float(std * math.sqrt(252)),
        "rows": int(len(returns)),
    }


def _run_robustness(matrix: pd.DataFrame, daily: pd.DataFrame, variant: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    benchmark = str(variant.get("benchmark") or "DBC").upper()
    lookback_rows = []
    for short, long in ((21, 63), (21, 126), (63, 126)):
        try:
            _, _, _, lookback_metrics = _run_variant_backtest(matrix, variant, short, long, 5.0)
            lookback_rows.append({"short_lookback": short, "long_lookback": long, "status": "COMPLETED", "metrics": lookback_metrics})
        except Exception as exc:
            lookback_rows.append({"short_lookback": short, "long_lookback": long, "status": "BLOCKED", "reason": str(exc)})
    cost_rows = []
    for cost_bps in (0.0, 5.0, 10.0, 25.0):
        try:
            _, _, _, cost_metrics = _run_variant_backtest(matrix, variant, 21, 63, cost_bps)
            cost_rows.append({"cost_bps_per_side": cost_bps, "status": "COMPLETED", "metrics": cost_metrics})
        except Exception as exc:
            cost_rows.append({"cost_bps_per_side": cost_bps, "status": "BLOCKED", "reason": str(exc)})
    daily_data = daily.copy()
    daily_data["date"] = pd.to_datetime(daily_data["date"])
    recent_cutoff = daily_data["date"].max() - pd.DateOffset(years=1)
    recent = daily_data[daily_data["date"] >= recent_cutoff]
    rolling_vol = daily_data["net_return"].rolling(63, min_periods=21).std()
    high_vol = daily_data[rolling_vol >= rolling_vol.quantile(0.75)]
    worst_drawdown_date = pd.to_datetime(daily_data.loc[(1.0 + daily_data["net_return"]).cumprod().div((1.0 + daily_data["net_return"]).cumprod().cummax()).sub(1.0).idxmin(), "date"])
    drawdown_window = daily_data[(daily_data["date"] >= worst_drawdown_date - pd.DateOffset(days=63)) & (daily_data["date"] <= worst_drawdown_date + pd.DateOffset(days=21))]
    benchmark_metrics = _metrics_for_series(daily_data["benchmark_return"])
    base_sharpe = _finite_float(metrics.get("sharpe"))
    cost_25 = next((row for row in cost_rows if row["cost_bps_per_side"] == 25.0 and row["status"] == "COMPLETED"), None)
    cost_25_sharpe = _finite_float(((cost_25 or {}).get("metrics") or {}).get("sharpe"))
    pass_cost = bool(base_sharpe is not None and cost_25_sharpe is not None and cost_25_sharpe > 0 and cost_25_sharpe >= base_sharpe - 0.5)
    pass_lookback = sum(1 for row in lookback_rows if row["status"] == "COMPLETED" and _finite_float(row["metrics"].get("sharpe")) is not None and _finite_float(row["metrics"].get("sharpe")) > 0) >= 2
    return {
        "schema_version": "strategy_factory_variant_robustness_run_v1",
        "status": "COMPLETED",
        "variant_id": variant.get("variant_id"),
        "source_run_id": variant.get("source_run_id"),
        "lookback_sensitivity": lookback_rows,
        "cost_sensitivity": cost_rows,
        "benchmark_comparison": {
            "benchmark": benchmark,
            "strategy_metrics": metrics,
            "benchmark_metrics": benchmark_metrics,
            "status": "COMPLETED",
        },
        "stress_periods": {
            "recent_period": _metrics_for_series(recent["net_return"]),
            "high_vol_period": _metrics_for_series(high_vol["net_return"]),
            "drawdown_window": _metrics_for_series(drawdown_window["net_return"]),
            "worst_drawdown_date": str(worst_drawdown_date.date()),
        },
        "summary": {
            "cost_sensitivity_status": "PASS" if pass_cost else "WATCH",
            "lookback_sensitivity_status": "PASS" if pass_lookback else "WATCH",
            "benchmark_status": "PASS" if (_finite_float(metrics.get("annual_return")) or -1) > (_finite_float(benchmark_metrics.get("annual_return")) or 0) else "WATCH",
            "overall_status": "PASS" if pass_cost and pass_lookback and (base_sharpe or 0) >= 1.0 else "WATCH",
        },
        "generated_at": _now(),
    }


def _ml_supportive(ml: dict[str, Any]) -> bool:
    if ml.get("status") != "COMPLETED":
        return False
    quality = ml.get("prediction_quality") or {}
    direction = ml.get("direction_quality") or {}
    ic = _finite_float(quality.get("spearman_ic"))
    hit = _finite_float(direction.get("direction_hit_rate"))
    return bool((ic is not None and ic > 0.02) or (hit is not None and hit >= 0.53))


def _decision(variant: dict[str, Any], metrics: dict[str, Any], ml: dict[str, Any], robustness: dict[str, Any]) -> dict[str, Any]:
    sharpe = _finite_float(metrics.get("sharpe"))
    max_drawdown = _finite_float(metrics.get("max_drawdown"))
    proxy_only = variant.get("testability_status") == "PROXY_ONLY" or metrics.get("prototype_proxy_only") is True
    robustness_pass = ((robustness.get("summary") or {}).get("overall_status") == "PASS")
    supportive_ml = _ml_supportive(ml)
    candidate = bool(not proxy_only and sharpe is not None and sharpe >= 1.0 and (max_drawdown is None or max_drawdown > -0.25) and robustness_pass and supportive_ml)
    if candidate:
        recommendation = "Candidate"
        reason = "Backtest, robustness, ML diagnostics, and data quality support admission consideration."
    elif sharpe is None:
        recommendation = "Blocked"
        reason = "Backtest metrics are unavailable."
    elif sharpe < 0.25 or (max_drawdown is not None and max_drawdown < -0.35):
        recommendation = "Modify"
        reason = "Weak risk-adjusted performance or drawdown severity requires changes before broader testing."
    else:
        recommendation = "Watch"
        reason = "Pipeline completed, but proxy-only data and incomplete robustness/ML evidence do not support Candidate status."
    return {
        "schema_version": "strategy_factory_variant_decision_v1",
        "status": "COMPLETED" if recommendation != "Blocked" else "BLOCKED",
        "variant_id": variant.get("variant_id"),
        "source_run_id": variant.get("source_run_id"),
        "decision": recommendation,
        "recommendation": recommendation,
        "candidate": candidate,
        "reason": reason,
        "evidence_flags": {
            "proxy_only": proxy_only,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "ml_supportive": supportive_ml,
            "robustness_overall": (robustness.get("summary") or {}).get("overall_status"),
        },
        "non_actions": ["NO_LIVE_TRADING", "NO_PAPER_LEDGER_MUTATION", "NO_DEPLOY", "NO_DASHBOARD_LAYOUT_CHANGE", "NO_VARIANT_RANKING"],
        "generated_at": _now(),
    }


def _write_evidence_report(path: Path, variant: dict[str, Any], backtest: dict[str, Any], metrics: dict[str, Any], ml: dict[str, Any], robustness: dict[str, Any], decision: dict[str, Any]) -> None:
    def fmt(value: Any) -> str:
        number = _finite_float(value)
        return f"{number:.6f}" if number is not None else str(value)

    lines = [
        f"# Variant Evidence Report - {variant.get('variant_id')}",
        "",
        f"Decision: {decision.get('recommendation')}",
        "",
        "## Variant",
        f"- Source run: {variant.get('source_run_id')}",
        f"- Name: {variant.get('variant_name')}",
        f"- Thesis: {variant.get('thesis')}",
        f"- Signal: {variant.get('signal_formula')}",
        f"- Theme: {variant.get('theme', 'Missing Evidence')}",
        f"- Universe/proxy: {', '.join(variant.get('universe_or_proxy') or [])}",
        f"- Benchmark: {variant.get('benchmark')}",
        "",
        "## Backtest",
        f"- Status: {backtest.get('status')}",
        f"- Provider: {backtest.get('source_provider')}",
        f"- Local data only: {backtest.get('local_data_only')}",
        f"- Date range: {metrics.get('date_range')}",
        f"- Annual return: {fmt(metrics.get('annual_return'))}",
        f"- Sharpe: {fmt(metrics.get('sharpe'))}",
        f"- Max drawdown: {fmt(metrics.get('max_drawdown'))}",
        f"- Volatility: {fmt(metrics.get('volatility'))}",
        f"- Benchmark annual return: {fmt(metrics.get('benchmark_annual_return'))}",
        "",
        "## ML Diagnostics",
        f"- Status: {ml.get('status')}",
        f"- Evidence status: {ml.get('ml_evidence_status', 'REAL_COMPUTED_ML' if ml.get('status') == 'COMPLETED' else 'MISSING_EVIDENCE')}",
        f"- Model: {ml.get('model', 'Unavailable')}",
        f"- Prediction quality: {json.dumps(ml.get('prediction_quality', {}), sort_keys=True)}",
        f"- Direction quality: {json.dumps(ml.get('direction_quality', {}), sort_keys=True)}",
        f"- Blocked reason: {ml.get('reason', '')}",
        "",
        "## Robustness",
        f"- Status: {robustness.get('status')}",
        f"- Overall: {(robustness.get('summary') or {}).get('overall_status')}",
        f"- Cost sensitivity: {(robustness.get('summary') or {}).get('cost_sensitivity_status')}",
        f"- Lookback sensitivity: {(robustness.get('summary') or {}).get('lookback_sensitivity_status')}",
        f"- Benchmark comparison: {(robustness.get('summary') or {}).get('benchmark_status')}",
        "",
        "## Limitations",
        "- Research-only prototype using local public/proxy data.",
        "- Data is not point-in-time clean and is not suitable for portfolio admission by itself.",
        "- Candidate status is blocked by proxy-only evidence unless future data quality and robustness improve.",
        "- No deployment, live trading, paper ledger mutation, or variant ranking was performed.",
        "",
        "## Final Decision",
        f"{decision.get('recommendation')}: {decision.get('reason')}",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def evaluate_single_variant(root: Path, source_run_id: str, variant_id: str = VARIANT_ID) -> dict[str, Any]:
    variant_path = _variant_dir(root, source_run_id, variant_id) / "variant_spec.json"
    variant = _read_json(variant_path, {})
    if not variant:
        raise ValueError(f"Variant spec not found or unreadable: {variant_path}")
    if variant.get("variant_id") != variant_id:
        raise ValueError(f"Variant spec id mismatch: expected {variant_id}, found {variant.get('variant_id')}")
    if source_run_id != variant.get("source_run_id"):
        raise ValueError(f"Source run id mismatch: expected {source_run_id}, found {variant.get('source_run_id')}")

    evaluation_dir = variant_path.parent / "evaluation"
    paths = _evaluation_paths(evaluation_dir)
    us_stock_real_backtest = (
        variant.get("theme") == THEME_US_STOCK_MOMENTUM_QUALITY and variant_id == "US_STOCK_MOMENTUM_12_1_TOP50_V1"
    ) or (
        variant.get("theme") == THEME_US_STOCK_LOW_VOL_DEFENSIVE
        and variant_id in {"US_STOCK_LOW_VOL_63D_TOP20_V1", "US_STOCK_LOW_VOL_126D_TOP20_V1", "US_STOCK_LOW_VOL_BETA_FILTER_TOP20_V1"}
    )
    if us_stock_real_backtest:
        phase3d = run_us_stock_low_vol_backtest(root, variant, evaluation_dir) if variant.get("theme") == THEME_US_STOCK_LOW_VOL_DEFENSIVE else run_us_stock_12_1_backtest(root, variant, evaluation_dir)
        if phase3d.get("status") == "COMPLETED":
            summary = phase3d["summary"]
            is_low_vol = variant.get("theme") == THEME_US_STOCK_LOW_VOL_DEFENSIVE
            daily = phase3d["daily"].copy()
            daily["variant_id"] = variant_id
            daily["position"] = ",".join(summary["tickers_used"][: min(10, len(summary["tickers_used"]))])
            daily["signal_date"] = daily["date"]
            daily["execution_date"] = daily["date"]
            daily["base_cost_bps_per_side"] = summary["metrics"].get("cost_assumption_bps_per_side")
            _write_csv(Path(paths["daily_returns"]), ["date", "variant_id", "gross_return", "transaction_cost", "cost_drag", "net_return", "turnover", "benchmark_return", "position", "signal_date", "execution_date", "base_cost_bps_per_side"], daily.to_dict("records"))
            strategy_equity = (1.0 + daily["net_return"].astype(float)).cumprod()
            benchmark_equity = (1.0 + daily["benchmark_return"].astype(float)).cumprod()
            equity = pd.DataFrame({"date": daily["date"], "strategy_equity": strategy_equity, "benchmark_equity": benchmark_equity})
            drawdown = pd.DataFrame({"date": daily["date"], "drawdown": strategy_equity / strategy_equity.cummax() - 1.0})
            _write_csv(Path(paths["equity_curve"]), list(equity.columns), equity.to_dict("records"))
            _write_csv(Path(paths["drawdown"]), list(drawdown.columns), drawdown.to_dict("records"))
            metrics = {
                "schema_version": "strategy_factory_variant_metrics_v1",
                "status": "COMPLETED",
                "theme": variant.get("theme"),
                "benchmark": "SPY",
                "universe": summary["tickers_used"],
                "input_universe_path": summary["input_universe_path"],
                "universe_count": summary["universe_count"],
                "universe_limitations": summary["universe_limitations"],
                "price_data_source": summary["price_data_source"],
                "price_data_path": summary["price_data_path"],
                "data_quality_status": summary["data_quality_status"],
                "strategy_evidence_family": "LOW_VOL_DEFENSIVE" if is_low_vol else "MOMENTUM_QUALITY",
                "annual_return": summary["metrics"].get("annual_return"),
                "volatility": summary["metrics"].get("volatility"),
                "sharpe": summary["metrics"].get("sharpe"),
                "max_drawdown": summary["metrics"].get("max_drawdown"),
                "turnover": summary["metrics"].get("turnover"),
                "turnover_value": summary["metrics"].get("turnover_value"),
                "turnover_unit": summary["metrics"].get("turnover_unit"),
                "turnover_frequency": summary["metrics"].get("turnover_frequency"),
                "turnover_definition": summary["metrics"].get("turnover_definition"),
                "average_rebalance_turnover": summary["metrics"].get("average_rebalance_turnover"),
                "annualized_turnover": summary["metrics"].get("annualized_turnover"),
                "cumulative_turnover": summary["metrics"].get("cumulative_turnover"),
                "rebalance_frequency_per_year": summary["metrics"].get("rebalance_frequency_per_year"),
                "benchmark_annual_return": summary["metrics"].get("benchmark_annual_return"),
                "excess_return": summary["metrics"].get("excess_return"),
                "rows": summary["metrics"].get("rows"),
                "date_range": summary["metrics"].get("date_range"),
                "rebalance_periods": summary["rebalance_periods"],
                "holdings_per_rebalance": summary["holdings_per_rebalance"],
                "cost_assumption_bps_per_side": summary["metrics"].get("cost_assumption_bps_per_side"),
                "prototype_proxy_only": False,
                "generated_at": _now(),
            }
            if is_low_vol:
                metrics["feature_definition"] = summary["signal_definition"]
                metrics["ranking_evidence_text"] = "Ranks U.S. stocks by lower realized volatility; no momentum-quality or ETF/copper scoring is used."
            else:
                metrics["quality_evidence_status"] = "MISSING_EVIDENCE"
                metrics["quality_evidence_reason"] = "Phase 3D minimal backtest uses price-only 12-1 momentum; profitability, ROE, and gross-margin fields were not supplied."
            backtest = {
                "schema_version": "strategy_factory_variant_backtest_run_v1",
                "status": "COMPLETED",
                "source_run_id": source_run_id,
                "variant_id": variant_id,
                "variant_spec_path": str(variant_path),
                "source_provider": summary["price_data_source"],
                "local_data_only": summary["price_data_source"] == "LOCAL_PRICE_CACHE",
                "input_universe_path": summary["input_universe_path"],
                "price_data_source_path": summary["price_data_path"],
                "universe": summary["tickers_used"],
                "universe_count": summary["universe_count"],
                "universe_limitations": summary["universe_limitations"],
                "benchmark": "SPY",
                "testability_status": variant.get("testability_status"),
                "signal": summary["signal_definition"],
                "date_range": summary["metrics"].get("date_range"),
                "rows": summary["metrics"].get("rows"),
                "cost_assumption_bps_per_side": summary["metrics"].get("cost_assumption_bps_per_side"),
                "turnover_definition": summary.get("turnover_definition") or summary["metrics"].get("turnover_definition"),
                "live_trading": "NOT_TOUCHED",
                "paper_ledger": "NOT_MUTATED",
                "deploy": "NOT_RUN",
                "artifacts": paths,
                "generated_at": _now(),
            }
            _write_json(Path(paths["metrics"]), metrics)
            _write_json(Path(paths["backtest_run"]), backtest)
            ml_reason = (
                "No ML evidence available for U.S. Stock Low Vol Defensive; no fitted low-vol model, train/test split, feature matrix, target, or out-of-sample metric exists."
                if is_low_vol
                else "No ML evidence available for U.S. Stock Momentum + Quality; U.S. stock ML pipeline has not been implemented."
            )
            ml = _write_missing_ml(paths, ml_reason, variant)
            robustness = {
                "schema_version": "strategy_factory_variant_robustness_run_v1",
                "status": "COMPLETED",
                "variant_id": variant_id,
                "source_run_id": source_run_id,
                "summary": {
                    "overall_status": "WATCH",
                    "cost_sensitivity_status": "NOT_RUN_PHASE3D_MINIMAL",
                    "lookback_sensitivity_status": "NOT_RUN_PHASE3D_MINIMAL",
                    "benchmark_status": "AVAILABLE" if metrics.get("benchmark_annual_return") != "Missing Evidence" else "MISSING_EVIDENCE",
                },
                "limitations": summary["universe_limitations"],
                "generated_at": _now(),
            }
            decision = {
                "schema_version": "strategy_factory_variant_decision_v1",
                "status": "COMPLETED",
                "source_run_id": source_run_id,
                "variant_id": variant_id,
                "decision": "Watch",
                "recommendation": "Watch",
                "candidate": False,
                "reason": (
                    "Low-vol defensive prototype produced minimal public-fallback U.S. stock backtest evidence; not institutional validation."
                    if is_low_vol
                    else "Phase 3D produced minimal public-fallback U.S. stock backtest evidence; not institutional validation."
                ),
                "generated_at": _now(),
            }
            readiness = write_variant_readiness(evaluation_dir, variant, backtest, metrics, ml, paths)
            decision.update({"automation_ready": readiness["readiness"]["automation_ready"], "automation_block_reason": readiness["readiness"]["automation_block_reason"]})
            _write_json(Path(paths["robustness_run"]), robustness)
            _write_json(Path(paths["decision"]), decision)
            _write_evidence_report(Path(paths["evidence_report"]), variant, backtest, metrics, ml, robustness, decision)
            return {
                "schema_version": "strategy_factory_variant_evaluation_v1",
                "status": "COMPLETED",
                "source_run_id": source_run_id,
                "variant_id": variant_id,
                "evaluation_dir": str(evaluation_dir),
                "artifacts": paths,
                "metrics": metrics,
                "ml_status": ml.get("status"),
                "robustness_status": robustness.get("status"),
                "decision": decision,
                "non_actions": ["NO_LIVE_TRADING", "NO_PAPER_LEDGER_MUTATION", "NO_DEPLOY", "NO_DASHBOARD_LAYOUT_CHANGE", "NO_ML_RUN", "NO_AUTOMATION"],
                "generated_at": _now(),
            }
        blocked = _blocked_outputs(paths, source_run_id, variant, phase3d.get("reason") or "DATA_MISSING: U.S. stock backtest data unavailable.")
        return blocked
    required = _required_symbols_for_variant(variant)

    provider = select_local_provider(data_root())
    prices = provider.get_price_history(required, None, None)
    available = sorted(set(prices["symbol"].astype(str).str.upper())) if not prices.empty and "symbol" in prices.columns else []
    missing = [symbol for symbol in required if symbol not in available]
    if missing:
        return _blocked_outputs(paths, source_run_id, variant, f"Missing required local symbols: {', '.join(missing)}")

    matrix = _price_matrix(prices, required)
    try:
        daily, equity, drawdown, metrics = _run_variant_backtest(matrix, variant)
    except Exception as exc:
        return _blocked_outputs(paths, source_run_id, variant, str(exc))

    _write_csv(Path(paths["daily_returns"]), list(daily.columns), daily.to_dict("records"))
    _write_csv(Path(paths["equity_curve"]), list(equity.columns), equity.to_dict("records"))
    _write_csv(Path(paths["drawdown"]), list(drawdown.columns), drawdown.to_dict("records"))
    _write_json(Path(paths["metrics"]), metrics)
    backtest = {
        "schema_version": "strategy_factory_variant_backtest_run_v1",
        "status": "COMPLETED",
        "source_run_id": source_run_id,
        "variant_id": variant_id,
        "variant_spec_path": str(variant_path),
        "source_provider": getattr(provider, "provider_name", "LOCAL"),
        "local_data_only": True,
        "input_universe_path": str(getattr(provider, "root", data_root()) / "security_master" / "current_us_equity_universe.csv"),
        "price_data_source_path": str(getattr(provider, "root", data_root()) / "prices" / "daily_ohlcv.csv"),
        "universe": [str(symbol).upper() for symbol in variant.get("universe_or_proxy") or []],
        "benchmark": str(variant.get("benchmark") or "").upper(),
        "testability_status": variant.get("testability_status"),
        "signal": variant.get("signal_formula"),
        "date_range": metrics.get("date_range"),
        "rows": metrics.get("rows"),
        "cost_assumption_bps_per_side": metrics.get("cost_assumption_bps_per_side"),
        "live_trading": "NOT_TOUCHED",
        "paper_ledger": "NOT_MUTATED",
        "deploy": "NOT_RUN",
        "generated_at": _now(),
        "artifacts": paths,
    }
    _write_json(Path(paths["backtest_run"]), backtest)

    ml_artifacts = {
        "daily_returns": paths["daily_returns"],
        "ml_diagnostics_run": paths["ml_diagnostics_run"],
        "feature_importance_csv": paths["feature_importance_csv"],
        "feature_importance_json": paths["feature_importance_json"],
        "prediction_quality": paths["prediction_quality"],
        "train_test_split": paths["train_test_split"],
        "leakage_check": paths["leakage_check"],
    }
    if variant.get("theme") == THEME_ETF_MOMENTUM_ROTATION:
        ml = _write_missing_ml(paths, "No ML evidence available for ETF Momentum Rotation; ETF ML pipeline has not been implemented.", variant)
    elif variant.get("theme") == THEME_US_STOCK_MOMENTUM_QUALITY:
        ml = _write_missing_ml(paths, "No ML evidence available for U.S. Stock Momentum + Quality; U.S. stock ML pipeline has not been implemented.", variant)
    else:
        ml = run_current_run_ml_diagnostics(evaluation_dir, ml_artifacts, backtest, metrics)
    robustness = _run_robustness(matrix, daily, variant, metrics)
    decision = _decision(variant, metrics, ml, robustness)
    readiness = write_variant_readiness(evaluation_dir, variant, backtest, metrics, ml, paths)
    decision.update(
        {
            "automation_ready": readiness["readiness"]["automation_ready"],
            "automation_block_reason": readiness["readiness"]["automation_block_reason"],
        }
    )
    _write_json(Path(paths["robustness_run"]), robustness)
    _write_json(Path(paths["decision"]), decision)
    _write_evidence_report(Path(paths["evidence_report"]), variant, backtest, metrics, ml, robustness, decision)
    return {
        "schema_version": "strategy_factory_variant_evaluation_v1",
        "status": "COMPLETED",
        "source_run_id": source_run_id,
        "variant_id": variant_id,
        "evaluation_dir": str(evaluation_dir),
        "artifacts": paths,
        "metrics": metrics,
        "ml_status": ml.get("status"),
        "robustness_status": robustness.get("status"),
        "decision": decision,
        "non_actions": ["NO_LIVE_TRADING", "NO_PAPER_LEDGER_MUTATION", "NO_DEPLOY", "NO_DASHBOARD_LAYOUT_CHANGE", "NO_ALL_VARIANT_EVALUATION", "NO_VARIANT_RANKING"],
        "generated_at": _now(),
    }


def evaluate_all_variants(root: Path, source_run_id: str) -> dict[str, Any]:
    variants_dir = _run_dir(root, source_run_id) / "variants"
    registry_path = variants_dir / "variant_registry.json"
    registry = _read_json(registry_path, {})
    if not registry:
        raise ValueError(f"Variant registry not found or unreadable: {registry_path}")
    variants = registry.get("variants") or []
    results = []
    for row in variants:
        variant_id = str(row.get("variant_id") or "")
        if not variant_id:
            continue
        try:
            result = evaluate_single_variant(root, source_run_id, variant_id)
        except Exception as exc:
            variant = _read_json(variants_dir / variant_id / "variant_spec.json", {"variant_id": variant_id, "source_run_id": source_run_id})
            paths = _evaluation_paths(variants_dir / variant_id / "evaluation")
            result = _blocked_outputs(paths, source_run_id, variant, str(exc))
            result["variant_id"] = variant_id
        metrics = result.get("metrics") or _read_json(Path((result.get("artifacts") or {}).get("metrics", "")), {})
        decision = result.get("decision") or _read_json(Path((result.get("artifacts") or {}).get("decision", "")), {})
        ml = _read_json(Path((result.get("artifacts") or {}).get("ml_diagnostics_run", "")), {})
        robustness = _read_json(Path((result.get("artifacts") or {}).get("robustness_run", "")), {})
        results.append(
            {
                "variant_id": variant_id,
                "status": result.get("status"),
                "evaluation_dir": str(variants_dir / variant_id / "evaluation"),
                "sharpe": metrics.get("sharpe"),
                "annual_return": metrics.get("annual_return"),
                "max_drawdown": metrics.get("max_drawdown"),
                "ml_status": ml.get("status"),
                "ml_reason": ml.get("reason"),
                "robustness_status": robustness.get("status"),
                "robustness_overall": (robustness.get("summary") or {}).get("overall_status"),
                "decision": decision.get("recommendation") or decision.get("decision"),
                "blocked_reason": result.get("reason") or metrics.get("reason"),
            }
        )
    return {
        "schema_version": "strategy_factory_gate3b_all_variant_evaluation_v1",
        "status": "COMPLETED",
        "source_run_id": source_run_id,
        "variants_attempted": len(variants),
        "variants_evaluated": len(results),
        "results": results,
        "non_actions": ["NO_LIVE_TRADING", "NO_PAPER_LEDGER_MUTATION", "NO_DEPLOY", "NO_DASHBOARD_LAYOUT_CHANGE", "NO_VARIANT_RANKING"],
        "generated_at": _now(),
    }
