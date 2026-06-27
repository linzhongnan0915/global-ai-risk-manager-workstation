"""Strategy Factory current-run intelligence layer.

The V1 intelligence layer reads existing current_run artifacts and writes
planning, validation, and decision artifacts. It does not change strategy
definitions, ledger state, or execution state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path
from typing import Any
import csv
import json
import math

import pandas as pd

from src.strategies.strategy_factory_data import data_root, select_local_provider


INTELLIGENCE_ARTIFACT_KEYS = {
    "intelligence_plan": "intelligence_plan.json",
    "strategy_type_classification": "strategy_type_classification.json",
    "feature_plan": "feature_plan.json",
    "model_plan": "model_plan.json",
    "robustness_plan": "robustness_plan.json",
    "robustness_run": "robustness_run.json",
    "lookback_sensitivity_csv": "lookback_sensitivity.csv",
    "lookback_sensitivity_json": "lookback_sensitivity.json",
    "cost_sensitivity_csv": "cost_sensitivity.csv",
    "cost_sensitivity_json": "cost_sensitivity.json",
    "rebalance_sensitivity_csv": "rebalance_sensitivity.csv",
    "rebalance_sensitivity_json": "rebalance_sensitivity.json",
    "benchmark_comparison_csv": "benchmark_comparison.csv",
    "benchmark_comparison_json": "benchmark_comparison.json",
    "stress_period_summary": "stress_period_summary.json",
    "ml_lift_vs_rule_signal": "ml_lift_vs_rule_signal.json",
    "robustness_report": "robustness_report.md",
    "validation_scorecard": "validation_scorecard.json",
    "decision_scorecard": "decision_scorecard.json",
    "intelligence_report": "intelligence_report.md",
}


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


def _write_csv(path: Path, rows: list[dict[str, Any]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _selected_text(run_manifest: dict[str, Any]) -> str:
    chunks = [
        " ".join(str(x) for x in run_manifest.get("selected_material_names", [])),
        " ".join(str(x) for x in run_manifest.get("generated_artifacts", {}).get("candidate_ideas", [])),
    ]
    generated = run_manifest.get("generated_artifacts", {})
    for key in ("test_spec", "material_summary", "current_run_report"):
        path = Path(str(generated.get(key) or ""))
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    for key in ("test_specs", "research_cards"):
        for value in generated.get(key) or []:
            path = Path(str(value))
            if path.is_file():
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks).lower()


def classify_strategy_type(run_manifest: dict[str, Any]) -> dict[str, Any]:
    text = _selected_text(run_manifest)
    signals = []
    if any(word in text for word in ("copper", "commodity", "commodities", "dbc", "usd", "macro")):
        signals.append("commodity/macro keywords found in selected material or test spec")
    if any(word in text for word in ("momentum", "trend", "moving average")):
        signals.append("trend or momentum language found")
    if any(word in text for word in ("volatility", "risk regime", "drawdown")):
        signals.append("risk regime or volatility language found")

    if "copper" in text or ("commodit" in text and ("momentum" in text or "trend" in text)):
        strategy_type = "commodity trend / macro proxy"
        confidence = "HIGH"
    elif "sector" in text and ("rotation" in text or "momentum" in text):
        strategy_type = "sector rotation"
        confidence = "MEDIUM"
    elif "equity" in text and "momentum" in text:
        strategy_type = "equity momentum"
        confidence = "MEDIUM"
    elif "reversal" in text or "mean reversion" in text:
        strategy_type = "reversal"
        confidence = "MEDIUM"
    elif "volatility" in text or "risk regime" in text:
        strategy_type = "volatility/risk regime"
        confidence = "MEDIUM"
    else:
        strategy_type = "generic/unknown"
        confidence = "LOW"
        signals.append("no strong strategy-family keywords found")

    return {
        "schema_version": "strategy_factory_strategy_type_classification_v1",
        "status": "COMPLETED",
        "strategy_type": strategy_type,
        "confidence": confidence,
        "evidence": signals,
        "generated_at": _now(),
    }


def generate_feature_plan(strategy_type: str, availability: dict[str, Any]) -> dict[str, Any]:
    available = set(str(x).upper() for x in availability.get("available_symbols", []))
    usable = set(str(x).upper() for x in availability.get("usable_symbols", []))
    benchmark = str(availability.get("benchmark_symbol") or "").upper()

    def row(name: str, status: str, rationale: str, source: str) -> dict[str, Any]:
        return {"feature": name, "status": status, "rationale": rationale, "source": source}

    features = []
    if strategy_type == "commodity trend / macro proxy":
        features.extend(
            [
                row("momentum_21d", "INCLUDED", "Short horizon trend captures recent copper proxy continuation.", "current_run daily returns"),
                row("momentum_63d", "INCLUDED", "Quarterly trend aligns with commodity cycle persistence without using future data.", "current_run daily returns"),
                row("momentum_126d", "PLANNED", "Six-month trend is relevant but not yet in the V0 ML feature matrix.", "current_run daily returns"),
                row("realized_volatility", "INCLUDED", "Commodity trend signals can degrade in unstable volatility regimes.", "current_run daily returns"),
                row("drawdown", "INCLUDED", "Drawdown describes trend break and risk state.", "current_run equity curve"),
                row("moving_average_trend", "INCLUDED", "Moving-average trend is an interpretable proxy for the rule signal.", "current_run equity curve"),
                row(
                    f"benchmark_relative_strength_vs_{benchmark or 'DBC/SPY'}",
                    "INCLUDED" if benchmark else "BLOCKED",
                    "Relative strength tests whether the copper proxy adds information beyond the benchmark.",
                    f"benchmark {benchmark or 'missing'}",
                ),
                row(
                    "usd_proxy_uup",
                    "INCLUDED" if "UUP" in available or "UUP" in usable else "PLANNED",
                    "Copper often has macro sensitivity to USD strength; include only when UUP exists in local data.",
                    "UUP local proxy data",
                ),
                row(
                    "commodity_basket_proxy_dbc",
                    "INCLUDED" if "DBC" in available or benchmark == "DBC" else "BLOCKED",
                    "DBC provides broad commodity context and benchmark comparison.",
                    "DBC local proxy data",
                ),
            ]
        )
    else:
        features.extend(
            [
                row("momentum_21d", "INCLUDED", "Baseline trend feature available from current-run returns.", "current_run daily returns"),
                row("realized_volatility", "INCLUDED", "Risk normalization feature available from current-run returns.", "current_run daily returns"),
                row("benchmark_relative_strength", "INCLUDED" if benchmark else "BLOCKED", "Compares strategy behavior to selected benchmark.", benchmark or "missing benchmark"),
            ]
        )

    return {
        "schema_version": "strategy_factory_feature_plan_v1",
        "status": "COMPLETED",
        "strategy_type": strategy_type,
        "features": features,
        "included_features": [item["feature"] for item in features if item["status"] == "INCLUDED"],
        "generated_at": _now(),
    }


def generate_model_plan(ml: dict[str, Any]) -> dict[str, Any]:
    sample_count = int(ml.get("sample_count") or 0)
    sklearn_available = find_spec("sklearn") is not None
    plans = []
    small_sample = sample_count and sample_count < 750
    plans.append(
        {
            "model": "linear_regression",
            "status": "SELECTED",
            "target": "next-period return",
            "rationale": "Interpretable baseline suitable for small and medium samples.",
        }
    )
    plans.append(
        {
            "model": "ridge_regression",
            "status": "SELECTED",
            "target": "next-period return",
            "rationale": "Regularized linear model reduces coefficient instability while remaining interpretable.",
        }
    )
    plans.append(
        {
            "model": "logistic_regression",
            "status": "SELECTED" if sample_count >= 120 else "BLOCKED",
            "target": "next-period direction",
            "rationale": "Directional target requires a classifier; chronological split only.",
            "blocked_reason": None if sample_count >= 120 else "At least 120 post-feature samples required.",
        }
    )
    nonlinear_status = "BLOCKED" if small_sample or not sklearn_available else "ELIGIBLE"
    nonlinear_reason = "Small sample: use linear/ridge only." if small_sample else ("sklearn unavailable." if not sklearn_available else "Package and sample size support a cautious diagnostic run.")
    for model in ("random_forest", "gradient_boosting"):
        plans.append(
            {
                "model": model,
                "status": nonlinear_status,
                "target": "next-period return",
                "rationale": "Nonlinear model only belongs in diagnostics when package and sample size support it.",
                "blocked_reason": None if nonlinear_status == "ELIGIBLE" else nonlinear_reason,
            }
        )
    return {
        "schema_version": "strategy_factory_model_plan_v1",
        "status": "COMPLETED",
        "sample_count": sample_count,
        "split_method": "chronological_no_shuffle",
        "shuffle_allowed": False,
        "models": plans,
        "generated_at": _now(),
    }


def _annualized_return(values: pd.Series) -> float | None:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return None
    cumulative = float((1.0 + values).prod())
    years = len(values) / 252.0
    return cumulative ** (1.0 / years) - 1.0 if years > 0 else None


def _sharpe(values: pd.Series) -> float | None:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if len(values) < 2:
        return None
    std = float(values.std())
    if std == 0.0:
        return None
    return float(values.mean() / std * math.sqrt(252))


def _max_drawdown_from_returns(values: pd.Series) -> float | None:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return None
    equity = (1.0 + values).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def _rebalance_due(dates: list[str], idx: int, frequency: str) -> bool:
    if idx <= 0:
        return True
    current = pd.Timestamp(dates[idx])
    previous = pd.Timestamp(dates[idx - 1])
    if frequency == "daily":
        return True
    if frequency == "weekly":
        return current.isocalendar().week != previous.isocalendar().week or current.year != previous.year
    if frequency == "quarterly":
        return current.quarter != previous.quarter or current.year != previous.year
    return current.month != previous.month or current.year != previous.year


def _rule_backtest(
    prices: list[float],
    benchmark_prices: list[float],
    dates: list[str],
    *,
    lookback: int = 63,
    rebalance_frequency: str = "monthly",
    cost_bps: float = 5.0,
) -> dict[str, Any]:
    if len(prices) <= lookback + 21 or len(benchmark_prices) != len(prices):
        return {"status": "BLOCKED", "reason": "Insufficient overlapping price observations for rule backtest."}
    returns = [0.0] + [prices[idx] / prices[idx - 1] - 1.0 for idx in range(1, len(prices))]
    benchmark_returns = [0.0] + [benchmark_prices[idx] / benchmark_prices[idx - 1] - 1.0 for idx in range(1, len(benchmark_prices))]
    rows = []
    position = 0.0
    for idx in range(lookback + 1, len(prices)):
        previous = position
        if _rebalance_due(dates, idx, rebalance_frequency):
            momentum = prices[idx - 1] / prices[idx - lookback] - 1.0
            vol_window = pd.Series(returns[max(1, idx - 20) : idx]).std() * math.sqrt(252)
            long_vol = pd.Series(returns[max(1, idx - 252) : idx]).std() * math.sqrt(252)
            position = 1.0 if momentum > 0.0 and (pd.isna(long_vol) or vol_window <= max(float(long_vol), 0.01)) else 0.0
        turnover = abs(position - previous)
        cost_drag = turnover * cost_bps / 10000.0
        gross = position * returns[idx]
        rows.append(
            {
                "date": dates[idx],
                "gross_return": gross,
                "net_return": gross - cost_drag,
                "benchmark_return": benchmark_returns[idx],
                "turnover": turnover,
                "position": position,
                "cost_drag": cost_drag,
            }
        )
    frame = pd.DataFrame(rows)
    return {
        "status": "COMPLETED",
        "observation_count": int(len(frame)),
        "annual_return": _annualized_return(frame["net_return"]),
        "sharpe": _sharpe(frame["net_return"]),
        "max_drawdown": _max_drawdown_from_returns(frame["net_return"]),
        "volatility": float(pd.to_numeric(frame["net_return"], errors="coerce").std() * math.sqrt(252)),
        "average_turnover": float(frame["turnover"].mean()),
        "benchmark_annual_return": _annualized_return(frame["benchmark_return"]),
        "return_correlation": float(frame["net_return"].corr(frame["benchmark_return"])),
        "rows": rows,
    }


def _load_price_matrix(backtest: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    universe = str(backtest.get("universe") or "").upper()
    benchmark = str(backtest.get("benchmark") or "DBC").upper()
    start = (backtest.get("test_period") or {}).get("start_date")
    end = (backtest.get("test_period") or {}).get("end_date")
    symbols = [symbol for symbol in [universe, benchmark, "DBC", "SPY"] if symbol]
    if not universe:
        return pd.DataFrame(), {"status": "BLOCKED", "reason": "Backtest universe symbol missing."}
    provider = select_local_provider()
    prices = provider.get_price_history(list(dict.fromkeys(symbols)), start, end)
    if prices.empty:
        return pd.DataFrame(), {"status": "BLOCKED", "reason": "Provider returned no price history for robustness symbols."}
    price_col = "adj_close" if "adj_close" in prices.columns else "close"
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.strftime("%Y-%m-%d")
    prices["symbol"] = prices["symbol"].astype(str).str.upper()
    prices[price_col] = pd.to_numeric(prices[price_col], errors="coerce")
    matrix = prices.pivot_table(index="date", columns="symbol", values=price_col, aggfunc="last").sort_index()
    return matrix, {"status": "COMPLETED", "universe": universe, "benchmark": benchmark, "price_col": price_col}


def _series_for(matrix: pd.DataFrame, universe: str, benchmark: str) -> tuple[list[float], list[float], list[str]]:
    if universe not in matrix.columns or benchmark not in matrix.columns:
        return [], [], []
    paired = matrix[[universe, benchmark]].dropna()
    return paired[universe].astype(float).tolist(), paired[benchmark].astype(float).tolist(), [str(idx)[:10] for idx in paired.index]


def _summary_row(test_name: str, variant: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "test": test_name,
        "variant": variant,
        "status": result.get("status"),
        "annual_return": result.get("annual_return"),
        "sharpe": result.get("sharpe"),
        "max_drawdown": result.get("max_drawdown"),
        "volatility": result.get("volatility"),
        "average_turnover": result.get("average_turnover"),
        "benchmark_annual_return": result.get("benchmark_annual_return"),
        "return_correlation": result.get("return_correlation"),
        "observation_count": result.get("observation_count"),
        "reason": result.get("reason"),
    }


def _write_sensitivity_pair(csv_path: Path, json_path: Path, payload: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    headers = [
        "test",
        "variant",
        "status",
        "annual_return",
        "sharpe",
        "max_drawdown",
        "volatility",
        "average_turnover",
        "benchmark_annual_return",
        "return_correlation",
        "observation_count",
        "reason",
    ]
    _write_csv(csv_path, rows, headers)
    _write_json(json_path, payload)


def _stress_summary_from_daily(daily_path: Path) -> dict[str, Any]:
    if not daily_path.is_file():
        return {"status": "BLOCKED", "reason": "daily_returns.csv missing."}
    daily = pd.read_csv(daily_path)
    if daily.empty:
        return {"status": "BLOCKED", "reason": "daily_returns.csv empty."}
    daily["date"] = pd.to_datetime(daily["date"])
    daily["net_return"] = pd.to_numeric(daily["net_return"], errors="coerce")
    daily = daily.dropna(subset=["date", "net_return"]).sort_values("date")
    if daily.empty:
        return {"status": "BLOCKED", "reason": "No valid return rows."}
    daily["rolling_vol_63d"] = daily["net_return"].rolling(63, min_periods=21).std() * math.sqrt(252)
    equity = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = equity / equity.cummax() - 1.0

    def period_payload(name: str, frame: pd.DataFrame) -> dict[str, Any]:
        if frame.empty:
            return {"period": name, "status": "BLOCKED", "reason": "No rows in period."}
        return {
            "period": name,
            "status": "COMPLETED",
            "start": str(frame["date"].iloc[0].date()),
            "end": str(frame["date"].iloc[-1].date()),
            "rows": int(len(frame)),
            "annual_return": _annualized_return(frame["net_return"]),
            "sharpe": _sharpe(frame["net_return"]),
            "max_drawdown": _max_drawdown_from_returns(frame["net_return"]),
        }

    recent_start = daily["date"].max() - pd.Timedelta(days=365)
    high_vol = daily[daily["rolling_vol_63d"] >= daily["rolling_vol_63d"].quantile(0.80)]
    worst_date = daily.loc[daily["drawdown"].idxmin(), "date"]
    drawdown = daily[(daily["date"] >= worst_date - pd.Timedelta(days=90)) & (daily["date"] <= worst_date + pd.Timedelta(days=90))]
    return {
        "schema_version": "strategy_factory_stress_period_summary_v1",
        "status": "COMPLETED",
        "periods": [
            period_payload("recent_1y", daily[daily["date"] >= recent_start]),
            period_payload("high_volatility_top_quintile", high_vol),
            period_payload("max_drawdown_window", drawdown),
        ],
        "generated_at": _now(),
    }


def _ml_lift_vs_rule_signal(daily_path: Path, ml: dict[str, Any]) -> dict[str, Any]:
    if not daily_path.is_file():
        return {"schema_version": "strategy_factory_ml_lift_vs_rule_signal_v1", "status": "BLOCKED", "reason": "daily_returns.csv missing."}
    daily = pd.read_csv(daily_path)
    required = {"date", "net_return", "position"}
    if not required.issubset(daily.columns):
        return {"schema_version": "strategy_factory_ml_lift_vs_rule_signal_v1", "status": "BLOCKED", "reason": "daily_returns.csv missing position or net_return columns."}
    daily["net_return"] = pd.to_numeric(daily["net_return"], errors="coerce")
    daily["position"] = pd.to_numeric(daily["position"], errors="coerce")
    daily["target_next_direction"] = (daily["net_return"].shift(-1) > 0).astype(float)
    daily["rule_prediction"] = (daily["position"] > 0).astype(float)
    scored = daily.dropna(subset=["target_next_direction", "rule_prediction"])
    if len(scored) < 20:
        return {"schema_version": "strategy_factory_ml_lift_vs_rule_signal_v1", "status": "BLOCKED", "reason": "Not enough rows for rule baseline comparison."}
    rule_hit = float((scored["target_next_direction"] == scored["rule_prediction"]).mean())
    ml_hit = _float((ml.get("direction_quality") or {}).get("direction_hit_rate"))
    lift = ml_hit - rule_hit if ml_hit is not None else None
    return {
        "schema_version": "strategy_factory_ml_lift_vs_rule_signal_v1",
        "status": "COMPLETED" if ml_hit is not None else "BLOCKED",
        "rule_baseline": "current rule position predicts next-period direction",
        "rule_direction_hit_rate": rule_hit,
        "ml_direction_hit_rate": ml_hit,
        "ml_lift": lift,
        "interpretation": "ML improves direction hit rate versus the rule baseline." if lift is not None and lift > 0 else "ML does not improve direction hit rate versus the rule baseline.",
        "sample_count": int(len(scored)),
        "generated_at": _now(),
    }


def run_robustness_execution(run_dir: Path, artifacts: dict[str, str], backtest: dict[str, Any], ml: dict[str, Any]) -> dict[str, Any]:
    paths = {key: str(run_dir / filename) for key, filename in INTELLIGENCE_ARTIFACT_KEYS.items()}
    if backtest.get("status") != "COMPLETED":
        blocked = {
            "schema_version": "strategy_factory_robustness_run_v1",
            "status": "BLOCKED",
            "reason": backtest.get("reason") or "Backtest did not complete; robustness cannot run.",
            "generated_at": _now(),
        }
        for key in (
            "robustness_run",
            "lookback_sensitivity_json",
            "cost_sensitivity_json",
            "rebalance_sensitivity_json",
            "benchmark_comparison_json",
            "stress_period_summary",
            "ml_lift_vs_rule_signal",
        ):
            _write_json(Path(paths[key]), blocked)
        for key in ("lookback_sensitivity_csv", "cost_sensitivity_csv", "rebalance_sensitivity_csv", "benchmark_comparison_csv"):
            _write_csv(Path(paths[key]), [], ["test", "variant", "status", "reason"])
        Path(paths["robustness_report"]).write_text(f"# Robustness Report\n\nStatus: BLOCKED\n\nReason: {blocked['reason']}\n", encoding="utf-8")
        return blocked

    matrix, matrix_status = _load_price_matrix(backtest)
    universe = matrix_status.get("universe")
    base_benchmark = matrix_status.get("benchmark")
    if matrix.empty or matrix_status.get("status") != "COMPLETED":
        blocked = {
            "schema_version": "strategy_factory_robustness_run_v1",
            "status": "BLOCKED",
            "reason": matrix_status.get("reason", "Price matrix unavailable."),
            "generated_at": _now(),
        }
        _write_json(Path(paths["robustness_run"]), blocked)
        Path(paths["robustness_report"]).write_text(f"# Robustness Report\n\nStatus: BLOCKED\n\nReason: {blocked['reason']}\n", encoding="utf-8")
        return blocked

    prices, benchmark_prices, dates = _series_for(matrix, universe, base_benchmark)
    lookback_rows = []
    lookback_results = []
    for lookback in (21, 63, 126):
        result = _rule_backtest(prices, benchmark_prices, dates, lookback=lookback, rebalance_frequency="monthly", cost_bps=5.0)
        row = _summary_row("lookback_sensitivity", f"{lookback}d", result)
        lookback_rows.append(row)
        lookback_results.append({**row, "lookback_days": lookback})
    lookback_payload = {"schema_version": "strategy_factory_lookback_sensitivity_v1", "status": "COMPLETED", "results": lookback_results, "generated_at": _now()}
    _write_sensitivity_pair(Path(paths["lookback_sensitivity_csv"]), Path(paths["lookback_sensitivity_json"]), lookback_payload, lookback_rows)

    cost_rows = []
    cost_results = []
    for cost in (0, 5, 10, 25):
        result = _rule_backtest(prices, benchmark_prices, dates, lookback=63, rebalance_frequency="monthly", cost_bps=float(cost))
        row = _summary_row("cost_sensitivity", f"{cost}bps", result)
        cost_rows.append(row)
        cost_results.append({**row, "cost_bps": cost})
    cost_payload = {"schema_version": "strategy_factory_cost_sensitivity_v1", "status": "COMPLETED", "results": cost_results, "generated_at": _now()}
    _write_sensitivity_pair(Path(paths["cost_sensitivity_csv"]), Path(paths["cost_sensitivity_json"]), cost_payload, cost_rows)

    rebalance_rows = []
    rebalance_results = []
    for frequency in ("weekly", "monthly", "quarterly"):
        result = _rule_backtest(prices, benchmark_prices, dates, lookback=63, rebalance_frequency=frequency, cost_bps=5.0)
        row = _summary_row("rebalance_sensitivity", frequency, result)
        rebalance_rows.append(row)
        rebalance_results.append({**row, "rebalance_frequency": frequency})
    rebalance_payload = {"schema_version": "strategy_factory_rebalance_sensitivity_v1", "status": "COMPLETED", "results": rebalance_results, "generated_at": _now()}
    _write_sensitivity_pair(Path(paths["rebalance_sensitivity_csv"]), Path(paths["rebalance_sensitivity_json"]), rebalance_payload, rebalance_rows)

    benchmark_rows = []
    benchmark_results = []
    for benchmark in ("DBC", "SPY"):
        bench_prices_for_symbol = _series_for(matrix, universe, benchmark)
        if not bench_prices_for_symbol[0]:
            result = {"status": "BLOCKED", "reason": f"{benchmark} benchmark data unavailable."}
        else:
            result = _rule_backtest(bench_prices_for_symbol[0], bench_prices_for_symbol[1], bench_prices_for_symbol[2], lookback=63, rebalance_frequency="monthly", cost_bps=5.0)
        row = _summary_row("benchmark_comparison", benchmark, result)
        benchmark_rows.append(row)
        benchmark_results.append({**row, "benchmark": benchmark})
    benchmark_payload = {"schema_version": "strategy_factory_benchmark_comparison_v1", "status": "COMPLETED", "results": benchmark_results, "generated_at": _now()}
    _write_sensitivity_pair(Path(paths["benchmark_comparison_csv"]), Path(paths["benchmark_comparison_json"]), benchmark_payload, benchmark_rows)

    stress = _stress_summary_from_daily(Path(artifacts.get("daily_returns", "")))
    ml_lift = _ml_lift_vs_rule_signal(Path(artifacts.get("daily_returns", "")), ml)
    _write_json(Path(paths["stress_period_summary"]), stress)
    _write_json(Path(paths["ml_lift_vs_rule_signal"]), ml_lift)

    robustness_run = {
        "schema_version": "strategy_factory_robustness_run_v1",
        "status": "COMPLETED",
        "run_id": backtest.get("run_id"),
        "universe": universe,
        "base_benchmark": base_benchmark,
        "lookback_sensitivity": lookback_payload,
        "cost_sensitivity": cost_payload,
        "rebalance_sensitivity": rebalance_payload,
        "benchmark_comparison": benchmark_payload,
        "stress_period_summary": stress,
        "ml_lift_vs_rule_signal": ml_lift,
        "artifacts": paths,
        "generated_at": _now(),
    }
    _write_json(Path(paths["robustness_run"]), robustness_run)
    write_robustness_report(Path(paths["robustness_report"]), robustness_run)
    return robustness_run


def write_robustness_report(path: Path, robustness_run: dict[str, Any]) -> None:
    if robustness_run.get("status") != "COMPLETED":
        path.write_text(
            "# Strategy Factory Robustness Report\n\n"
            f"Status: {robustness_run.get('status')}\n\n"
            f"Reason: {robustness_run.get('reason', 'Unavailable')}\n",
            encoding="utf-8",
        )
        return

    def rows(section: str) -> list[dict[str, Any]]:
        payload = robustness_run.get(section) or {}
        return payload.get("results") or []

    def line(row: dict[str, Any]) -> str:
        return (
            f"- {row.get('variant')}: {row.get('status')}; "
            f"Sharpe {row.get('sharpe')}; annual return {row.get('annual_return')}; "
            f"max drawdown {row.get('max_drawdown')}"
        )

    stress_lines = []
    for period in (robustness_run.get("stress_period_summary") or {}).get("periods", []):
        stress_lines.append(
            f"- {period.get('period')}: {period.get('status')}; "
            f"{period.get('start')} to {period.get('end')}; "
            f"Sharpe {period.get('sharpe')}; max drawdown {period.get('max_drawdown')}"
        )
    ml_lift = robustness_run.get("ml_lift_vs_rule_signal") or {}
    lines = [
        f"# Strategy Factory Robustness Report - {robustness_run.get('run_id')}",
        "",
        f"Status: {robustness_run.get('status')}",
        "",
        "## Lookback Sensitivity",
        *[line(row) for row in rows("lookback_sensitivity")],
        "",
        "## Cost Sensitivity",
        *[line(row) for row in rows("cost_sensitivity")],
        "",
        "## Rebalance Sensitivity",
        *[line(row) for row in rows("rebalance_sensitivity")],
        "",
        "## Benchmark Comparison",
        *[line(row) for row in rows("benchmark_comparison")],
        "",
        "## Stress Periods",
        *stress_lines,
        "",
        "## ML Lift vs Rule Signal",
        f"Rule hit rate: {ml_lift.get('rule_direction_hit_rate')}",
        f"ML hit rate: {ml_lift.get('ml_direction_hit_rate')}",
        f"ML lift: {ml_lift.get('ml_lift')}",
        f"Interpretation: {ml_lift.get('interpretation')}",
        "",
        "## Failures And Next Experiment",
        "Weak or unstable variants should be treated as modification evidence, not as a reason to upgrade the strategy.",
        "Next experiment: isolate the rule signal, run lookback/frequency grids on point-in-time vendor data, and compare against DBC/SPY/UUP-aware benchmarks.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _diagnostics_from_daily(daily_path: Path, split: dict[str, Any]) -> dict[str, Any]:
    if not daily_path.is_file():
        return {"status": "BLOCKED", "reason": "daily_returns.csv missing."}
    daily = pd.read_csv(daily_path)
    if daily.empty:
        return {"status": "BLOCKED", "reason": "daily_returns.csv empty."}
    daily["date"] = pd.to_datetime(daily["date"])
    for col in ("net_return", "gross_return", "cost_drag", "benchmark_return"):
        if col in daily.columns:
            daily[col] = pd.to_numeric(daily[col], errors="coerce")
    diagnostics: dict[str, Any] = {"status": "COMPLETED"}
    diagnostics["cost_sensitivity"] = {
        "zero_cost_annual_return": _annualized_return(daily.get("gross_return", daily["net_return"])),
        "base_cost_annual_return": _annualized_return(daily["net_return"]),
        "double_cost_annual_return": _annualized_return(daily["net_return"] - daily.get("cost_drag", 0.0)),
        "status": "COMPLETED",
    }
    diagnostics["benchmark_comparison"] = {
        "strategy_annual_return": _annualized_return(daily["net_return"]),
        "benchmark_annual_return": _annualized_return(daily["benchmark_return"]) if "benchmark_return" in daily else None,
        "return_correlation": float(daily["net_return"].corr(daily["benchmark_return"])) if "benchmark_return" in daily else None,
        "status": "COMPLETED" if "benchmark_return" in daily else "BLOCKED",
    }
    daily["year"] = daily["date"].dt.year.astype(str)
    yearly = daily.groupby("year")["net_return"].apply(lambda x: float((1.0 + x).prod() - 1.0)).reset_index()
    diagnostics["period_diagnostics"] = {
        "best_year": yearly.sort_values("net_return", ascending=False).head(1).to_dict("records"),
        "worst_year": yearly.sort_values("net_return", ascending=True).head(1).to_dict("records"),
        "status": "COMPLETED",
    }
    train_end = pd.to_datetime(split.get("train_end")) if split.get("train_end") else None
    test_start = pd.to_datetime(split.get("test_start")) if split.get("test_start") else None
    if train_end is not None and test_start is not None:
        train = daily[daily["date"] <= train_end]
        test = daily[daily["date"] >= test_start]
        diagnostics["train_test_performance_split"] = {
            "train_annual_return": _annualized_return(train["net_return"]),
            "train_sharpe": _sharpe(train["net_return"]),
            "test_annual_return": _annualized_return(test["net_return"]),
            "test_sharpe": _sharpe(test["net_return"]),
            "status": "COMPLETED",
        }
    else:
        diagnostics["train_test_performance_split"] = {"status": "BLOCKED", "reason": "train_test_split artifact missing dates."}
    return diagnostics


def generate_robustness_plan(artifacts: dict[str, str], split: dict[str, Any], robustness_run: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostics = _diagnostics_from_daily(Path(artifacts.get("daily_returns", "")), split)
    executed = robustness_run if isinstance(robustness_run, dict) else {}
    executed_completed = executed.get("status") == "COMPLETED"
    tests = [
        {"test": "lookback_sensitivity", "status": "COMPLETED" if executed_completed else "PLANNED", "runnable": True, "reason": "Run 21d/63d/126d rule variants against same provider data.", "result": executed.get("lookback_sensitivity")},
        {"test": "rebalance_frequency_sensitivity", "status": "COMPLETED" if executed_completed else "PLANNED", "runnable": True, "reason": "Compare weekly, monthly, and quarterly rebalance.", "result": executed.get("rebalance_sensitivity")},
        {"test": "transaction_cost_sensitivity", "status": diagnostics.get("cost_sensitivity", {}).get("status", "BLOCKED"), "runnable": True, "result": diagnostics.get("cost_sensitivity")},
        {"test": "benchmark_comparison", "status": "COMPLETED" if executed_completed else diagnostics.get("benchmark_comparison", {}).get("status", "BLOCKED"), "runnable": True, "result": executed.get("benchmark_comparison") or diagnostics.get("benchmark_comparison")},
        {"test": "stress_bad_period_check", "status": "COMPLETED" if executed_completed else diagnostics.get("period_diagnostics", {}).get("status", "BLOCKED"), "runnable": True, "result": executed.get("stress_period_summary") or diagnostics.get("period_diagnostics")},
        {"test": "train_test_performance_split", "status": diagnostics.get("train_test_performance_split", {}).get("status", "BLOCKED"), "runnable": True, "result": diagnostics.get("train_test_performance_split")},
        {"test": "ml_lift_vs_rule_signal", "status": "COMPLETED" if executed_completed else "PLANNED", "runnable": True, "reason": "Compare ML predictions against the explicit rule signal.", "result": executed.get("ml_lift_vs_rule_signal")},
    ]
    return {
        "schema_version": "strategy_factory_robustness_plan_v1",
        "status": "COMPLETED" if diagnostics.get("status") == "COMPLETED" else "BLOCKED",
        "tests": tests,
        "generated_at": _now(),
    }


def _score(status: str, reason: str, evidence: Any = None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "evidence": evidence}


def generate_validation_scorecard(
    availability: dict[str, Any],
    metrics: dict[str, Any],
    ml: dict[str, Any],
    leakage: dict[str, Any],
    split: dict[str, Any],
    robustness: dict[str, Any],
    robustness_run: dict[str, Any],
    classification: dict[str, Any],
) -> dict[str, Any]:
    decision = availability.get("decision")
    sharpe = _float(metrics.get("sharpe"))
    drawdown = _float(metrics.get("max_drawdown"))
    sample_count = int(ml.get("sample_count") or split.get("train_count") or 0) + int(split.get("test_count") or 0)
    ic = _float((ml.get("prediction_quality") or {}).get("spearman_ic"))
    hit_rate = _float((ml.get("direction_quality") or {}).get("direction_hit_rate"))
    benchmark = availability.get("benchmark_symbol") or metrics.get("benchmark")
    cost = next((x.get("result") for x in robustness.get("tests", []) if x.get("test") == "transaction_cost_sensitivity"), {}) or {}
    base_return = _float(cost.get("base_cost_annual_return"))
    double_cost_return = _float(cost.get("double_cost_annual_return"))
    lookback_results = ((robustness_run.get("lookback_sensitivity") or {}).get("results") or []) if isinstance(robustness_run, dict) else []
    cost_results = ((robustness_run.get("cost_sensitivity") or {}).get("results") or []) if isinstance(robustness_run, dict) else []
    benchmark_results = ((robustness_run.get("benchmark_comparison") or {}).get("results") or []) if isinstance(robustness_run, dict) else []
    ml_lift = _float(((robustness_run.get("ml_lift_vs_rule_signal") or {}) if isinstance(robustness_run, dict) else {}).get("ml_lift"))
    lookback_pass_count = sum(1 for row in lookback_results if _float(row.get("sharpe")) is not None and _float(row.get("sharpe")) > 0.25)
    high_cost = next((row for row in cost_results if row.get("cost_bps") == 25), None)
    high_cost_sharpe = _float((high_cost or {}).get("sharpe"))
    benchmark_completed = [row for row in benchmark_results if row.get("status") == "COMPLETED"]

    items = {
        "data_availability": _score("PASS" if decision in {"READY_TO_BACKTEST", "PROXY_ONLY"} else "BLOCKED", f"Data decision is {decision}.", decision),
        "proxy_quality": _score("WATCH" if decision == "PROXY_ONLY" else ("PASS" if decision == "READY_TO_BACKTEST" else "BLOCKED"), "Proxy-only data is useful for prototype research but weak for admission.", availability.get("usable_symbols")),
        "sample_length": _score("PASS" if sample_count >= 750 else ("WATCH" if sample_count >= 120 else "BLOCKED"), f"{sample_count} post-feature ML samples.", sample_count),
        "benchmark_validity": _score("PASS" if benchmark in {"DBC", "SPY"} else "WATCH", f"Benchmark is {benchmark or 'missing'}.", benchmark),
        "leakage_risk": _score("PASS" if leakage.get("status") == "PASS" else "FAIL", "Chronological split and next-period target checks.", leakage),
        "overfit_risk": _score("WATCH" if decision == "PROXY_ONLY" or sample_count < 1000 else "PASS", "Proxy-only and limited sample diagnostics increase overfit risk.", {"sample_count": sample_count, "data_decision": decision}),
        "ml_incremental_value": _score("WATCH" if (ic is not None and ic > 0.0) or (hit_rate is not None and hit_rate >= 0.53) else "FAIL", "ML signal quality is mixed and diagnostic only.", {"spearman_ic": ic, "direction_hit_rate": hit_rate}),
        "cost_sensitivity": _score("WATCH" if base_return is not None and double_cost_return is not None and double_cost_return < base_return else "PASS", "Higher costs reduce annualized return.", cost),
        "drawdown_severity": _score("PASS" if drawdown is not None and drawdown > -0.20 else ("WATCH" if drawdown is not None and drawdown > -0.30 else "FAIL"), f"Max drawdown is {drawdown}.", drawdown),
        "economic_logic_strength": _score("WATCH" if classification.get("strategy_type") == "commodity trend / macro proxy" else "BLOCKED", "Copper trend/macro logic is plausible but not causal proof.", classification.get("evidence")),
        "performance_strength": _score("WATCH" if sharpe is not None and sharpe >= 0.25 else "FAIL", f"Sharpe is {sharpe}.", sharpe),
        "lookback_robustness": _score("PASS" if lookback_pass_count == 3 else ("WATCH" if lookback_pass_count else "FAIL"), f"{lookback_pass_count}/3 lookback variants have Sharpe above 0.25.", lookback_results),
        "high_cost_robustness": _score("PASS" if high_cost_sharpe is not None and high_cost_sharpe > 0.25 else "WATCH", "25 bps cost variant checks fragility to higher costs.", high_cost),
        "benchmark_robustness": _score("PASS" if len(benchmark_completed) >= 2 else "WATCH", f"{len(benchmark_completed)}/2 benchmark comparisons completed.", benchmark_results),
        "ml_lift_vs_rule": _score("PASS" if ml_lift is not None and ml_lift > 0.0 else "WATCH", "ML must improve over the rule baseline before Candidate consideration.", (robustness_run.get("ml_lift_vs_rule_signal") or {}) if isinstance(robustness_run, dict) else {}),
    }
    return {
        "schema_version": "strategy_factory_validation_scorecard_v1",
        "status": "COMPLETED",
        "items": items,
        "summary": {
            "pass": sum(1 for item in items.values() if item["status"] == "PASS"),
            "watch": sum(1 for item in items.values() if item["status"] == "WATCH"),
            "fail": sum(1 for item in items.values() if item["status"] == "FAIL"),
            "blocked": sum(1 for item in items.values() if item["status"] == "BLOCKED"),
        },
        "generated_at": _now(),
    }


def generate_decision_scorecard(validation: dict[str, Any], metrics: dict[str, Any], availability: dict[str, Any], ml: dict[str, Any], robustness_run: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = validation.get("summary", {})
    sharpe = _float(metrics.get("sharpe"))
    decision = availability.get("decision")
    ml_ic = _float((ml.get("prediction_quality") or {}).get("spearman_ic"))
    robustness = robustness_run if isinstance(robustness_run, dict) else {}
    robustness_status = robustness.get("status")
    ml_lift = _float((robustness.get("ml_lift_vs_rule_signal") or {}).get("ml_lift"))
    validation_items = validation.get("items", {})
    robustness_supports_candidate = (
        robustness_status == "COMPLETED"
        and (validation_items.get("lookback_robustness") or {}).get("status") == "PASS"
        and (validation_items.get("high_cost_robustness") or {}).get("status") == "PASS"
        and (validation_items.get("benchmark_robustness") or {}).get("status") == "PASS"
        and ml_lift is not None
        and ml_lift > 0.0
    )
    reasons = []
    if summary.get("blocked", 0):
        recommendation = "Blocked"
        reasons.append("At least one required validation item is blocked.")
    elif summary.get("fail", 0) >= 2:
        recommendation = "Reject"
        reasons.append("Multiple validation items failed.")
    elif decision == "READY_TO_BACKTEST" and sharpe is not None and sharpe >= 1.0 and robustness_supports_candidate and (ml_ic is None or ml_ic >= 0.0):
        recommendation = "Candidate"
        reasons.append("Performance, robustness, ML lift, and data availability support Candidate review.")
    elif decision == "PROXY_ONLY" or (sharpe is not None and sharpe < 0.5):
        recommendation = "Watch"
        reasons.append("Proxy-only data and low Sharpe do not support Candidate.")
    elif not robustness_supports_candidate:
        recommendation = "Modify"
        reasons.append("Robustness, cost, benchmark, or ML-lift evidence does not support Candidate.")
    elif ml_ic is not None and ml_ic < 0.0:
        recommendation = "Modify"
        reasons.append("ML incremental value is weak or negative.")
    else:
        recommendation = "Watch"
        reasons.append("Evidence is not strong enough for Candidate.")
    return {
        "schema_version": "strategy_factory_decision_scorecard_v1",
        "status": "COMPLETED",
        "recommendation": recommendation,
        "candidate_allowed": recommendation == "Candidate",
        "reasons": reasons,
        "evidence_summary": {
            "data_decision": decision,
            "sharpe": sharpe,
            "ml_spearman_ic": ml_ic,
            "ml_lift_vs_rule": ml_lift,
            "robustness_status": robustness_status,
            "validation_summary": summary,
        },
        "generated_at": _now(),
    }


def write_intelligence_report(
    path: Path,
    run_manifest: dict[str, Any],
    classification: dict[str, Any],
    feature_plan: dict[str, Any],
    model_plan: dict[str, Any],
    robustness: dict[str, Any],
    validation: dict[str, Any],
    decision: dict[str, Any],
    metrics: dict[str, Any],
    ml: dict[str, Any],
    availability: dict[str, Any],
    robustness_run: dict[str, Any] | None = None,
) -> None:
    feature_lines = [
        f"- {item['feature']} ({item['status']}): {item['rationale']}"
        for item in feature_plan.get("features", [])
    ]
    model_lines = [
        f"- {item['model']} ({item['status']}): {item['rationale']}{' Reason: ' + item['blocked_reason'] if item.get('blocked_reason') else ''}"
        for item in model_plan.get("models", [])
    ]
    robustness_lines = [
        f"- {item['test']} ({item['status']}): {json.dumps(item.get('result') or item.get('reason') or {}, sort_keys=True)}"
        for item in robustness.get("tests", [])
    ]
    validation_lines = [
        f"- {name}: {item['status']} - {item['reason']}"
        for name, item in validation.get("items", {}).items()
    ]
    lines = [
        f"# Strategy Factory Intelligence Report - {run_manifest.get('run_id')}",
        "",
        f"Final recommendation: {decision.get('recommendation')}",
        "",
        "## Strategy Type",
        f"{classification.get('strategy_type')} ({classification.get('confidence')})",
        "",
        "## Economic Thesis",
        "The current evidence is consistent with a copper commodity trend / macro proxy thesis: use copper ETF proxy trend and risk state against a broad commodity benchmark. This is not causal proof.",
        "",
        "## Data / Proxy Adequacy",
        f"Data decision: {availability.get('decision')}. Usable symbols: {', '.join(availability.get('usable_symbols') or [])}. Benchmark: {availability.get('benchmark_symbol')}.",
        "Proxy-only data is adequate for prototype research, but not for institutional validation or portfolio admission.",
        "",
        "## Feature Rationale",
        *feature_lines,
        "",
        "## Model Rationale",
        "Chronological split only. Random shuffle is not allowed.",
        *model_lines,
        "",
        "## ML Result Interpretation",
        f"Primary model: {ml.get('model', 'Unavailable')}. Prediction quality: {json.dumps(ml.get('prediction_quality', {}), sort_keys=True)}. Direction quality: {json.dumps(ml.get('direction_quality', {}), sort_keys=True)}.",
        "The ML diagnostics are useful for ranking hypotheses and failure modes, not for proving alpha.",
        "",
        "## Robustness Findings",
        *robustness_lines,
        f"- Robustness run status: {(robustness_run or {}).get('status', 'Unavailable')}",
        f"- Robustness report: {(robustness_run or {}).get('artifacts', {}).get('robustness_report', 'Unavailable')}",
        "",
        "## Validation Scorecard",
        *validation_lines,
        "",
        "## Where It Made / Lost Money",
        f"See monthly returns and evidence report artifacts. Sharpe: {metrics.get('sharpe')}; max drawdown: {metrics.get('max_drawdown')}.",
        "",
        "## What Data Would Improve It",
        "- Boss/API or vendor OHLCV with stable adjusted history.",
        "- Point-in-time security master and ETF/proxy metadata.",
        "- Copper futures, inventories, curves, USD, rates, and macro releases with timestamps.",
        "- Rule-signal exports for ML lift vs rule-signal diagnostics.",
        "",
        "## Final Recommendation",
        f"{decision.get('recommendation')}: {', '.join(decision.get('reasons') or [])}",
        "",
        "## Next Experiment Suggestions",
        "- Run lookback sensitivity across 21d/63d/126d momentum.",
        "- Compare DBC, SPY, UUP-aware, and copper-only benchmarks.",
        "- Add explicit bad-period stress slices.",
        "- Export rule signal and compare ML lift against the rule signal.",
        "- Re-run with institutional point-in-time data before any admission discussion.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_current_run_intelligence(run_dir: Path, artifacts: dict[str, str]) -> dict[str, Any]:
    paths = {key: str(run_dir / filename) for key, filename in INTELLIGENCE_ARTIFACT_KEYS.items()}
    run_manifest = _read_json(run_dir / "run_manifest.json", {})
    availability = _read_json(Path(artifacts.get("data_availability", run_dir / "data_availability.json")), {})
    provider_status = _read_json(data_root() / "manifests" / "provider_status.json", {})
    inventory = _read_json(data_root() / "manifests" / "data_inventory.json", {})
    provider_symbols = provider_status.get("available_symbols") or []
    inventory_symbols = [
        symbol
        for dataset in inventory.get("datasets", [])
        for symbol in dataset.get("symbols", [])
    ]
    provider_symbols = [*provider_symbols, *inventory_symbols]
    if provider_symbols:
        availability = {
            **availability,
            "available_symbols": sorted(set([*(availability.get("available_symbols") or []), *provider_symbols])),
        }
    metrics = _read_json(Path(artifacts.get("metrics", run_dir / "metrics.json")), {})
    ml = _read_json(Path(artifacts.get("ml_diagnostics_run", run_dir / "ml_diagnostics_run.json")), {})
    backtest = _read_json(Path(artifacts.get("backtest_run", run_dir / "backtest_run.json")), {})
    leakage = _read_json(Path(artifacts.get("leakage_check", run_dir / "leakage_check.json")), {})
    split = _read_json(Path(artifacts.get("train_test_split", run_dir / "train_test_split.json")), {})

    classification = classify_strategy_type(run_manifest)
    feature_plan = generate_feature_plan(classification["strategy_type"], availability)
    model_plan = generate_model_plan(ml)
    robustness_run = run_robustness_execution(run_dir, {**artifacts, **paths}, backtest, ml)
    robustness = generate_robustness_plan({**artifacts, **paths}, split, robustness_run)
    validation = generate_validation_scorecard(availability, metrics, ml, leakage, split, robustness, robustness_run, classification)
    decision = generate_decision_scorecard(validation, metrics, availability, ml, robustness_run)
    intelligence_plan = {
        "schema_version": "strategy_factory_intelligence_plan_v1",
        "status": "COMPLETED",
        "run_id": run_manifest.get("run_id"),
        "stages": [
            "strategy_type_classification",
            "feature_plan",
            "model_plan",
            "robustness_plan",
            "robustness_run",
            "validation_scorecard",
            "decision_scorecard",
            "intelligence_report",
        ],
        "inputs": {
            "run_manifest": str(run_dir / "run_manifest.json"),
            "metrics": artifacts.get("metrics"),
            "ml_diagnostics_run": artifacts.get("ml_diagnostics_run"),
            "data_availability": artifacts.get("data_availability"),
        },
        "artifacts": paths,
        "generated_at": _now(),
    }

    _write_json(Path(paths["intelligence_plan"]), intelligence_plan)
    _write_json(Path(paths["strategy_type_classification"]), classification)
    _write_json(Path(paths["feature_plan"]), feature_plan)
    _write_json(Path(paths["model_plan"]), model_plan)
    _write_json(Path(paths["robustness_plan"]), robustness)
    _write_json(Path(paths["validation_scorecard"]), validation)
    _write_json(Path(paths["decision_scorecard"]), decision)
    write_intelligence_report(
        Path(paths["intelligence_report"]),
        run_manifest,
        classification,
        feature_plan,
        model_plan,
        robustness,
        validation,
        decision,
        metrics,
        ml,
        availability,
        robustness_run,
    )
    return {
        "schema_version": "strategy_factory_intelligence_run_v1",
        "status": "COMPLETED",
        "run_id": run_manifest.get("run_id"),
        "strategy_type": classification["strategy_type"],
        "recommendation": decision["recommendation"],
        "artifacts": paths,
        "robustness_status": robustness_run.get("status"),
        "validation_summary": validation["summary"],
        "generated_at": _now(),
    }
