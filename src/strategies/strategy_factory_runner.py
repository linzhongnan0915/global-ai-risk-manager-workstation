"""Local Strategy Factory current-run backtest and ML runner.

This runner is intentionally artifact-bound: it reads the selected-run
manifest/test spec and writes either real prototype evidence from local price
series or explicit BLOCKED artifacts. It never fabricates research metrics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import csv
import json
import math
import os

from src.strategies.strategy_factory_data import (
    DECISION_BLOCKED,
    DECISION_PROXY_ONLY,
    DECISION_READY,
    evaluate_availability,
    infer_data_requirements,
    load_proxy_mapping,
    select_local_provider,
    write_run_data_artifacts,
)
from src.strategies.strategy_factory_intelligence import INTELLIGENCE_ARTIFACT_KEYS, run_current_run_intelligence
from src.strategies.strategy_factory_ml import run_current_run_ml_diagnostics, write_evidence_report


METRIC_UNAVAILABLE = "Metric unavailable in artifact."
COPPER_SYMBOLS = {"CPER", "JJC", "COPPER", "HG", "HG=F", "DBB"}
BENCHMARK_SYMBOLS = {"DBC", "SPY", "BCOM", "COMMODITIES", "BENCHMARK"}
THEME_COMMODITY_PROXY_TREND = "commodity_proxy_trend"
THEME_ETF_MOMENTUM_ROTATION = "etf_momentum_rotation"
THEME_US_STOCK_MOMENTUM_QUALITY = "us_stock_cross_sectional_momentum_quality"
THEME_UNKNOWN_REVIEW_REQUIRED = "unknown_review_required"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, headers: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def _factory_root(root: Path) -> Path:
    return root / "output" / "strategy_factory"


def _state_path(root: Path) -> Path:
    return _factory_root(root) / "state.json"


def _latest_run_manifest_path(root: Path) -> Path | None:
    state = _read_json(_state_path(root), {})
    latest = state.get("latest_run") if isinstance(state, dict) else {}
    path = Path(str(latest.get("run_manifest_path") or "")) if latest else None
    if path and path.is_file():
        return path
    runs_root = _factory_root(root) / "runs"
    manifests = sorted(runs_root.glob("*/run_manifest.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return manifests[0] if manifests else None


def _selected_test_spec_text(run_manifest: dict[str, Any]) -> tuple[str, str | None]:
    generated = run_manifest.get("generated_artifacts") if isinstance(run_manifest.get("generated_artifacts"), dict) else {}
    paths = generated.get("test_specs") if isinstance(generated.get("test_specs"), list) else []
    for value in paths:
        path = Path(str(value))
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace"), str(path)
    return "", None


def _run_text(run_manifest: dict[str, Any]) -> str:
    text, _ = _selected_test_spec_text(run_manifest)
    generated = run_manifest.get("generated_artifacts") if isinstance(run_manifest.get("generated_artifacts"), dict) else {}
    for key in ("material_summary", "extracted_ideas"):
        path = Path(str(generated.get(key) or ""))
        if path.is_file():
            text += "\n" + path.read_text(encoding="utf-8", errors="replace")
    text += "\n" + " ".join(str(name) for name in run_manifest.get("selected_material_names", []))
    return text.lower()


def _market_data_candidates(root: Path) -> list[Path]:
    explicit = os.environ.get("STRATEGY_FACTORY_MARKET_DATA_CSV")
    candidates: list[Path] = [Path(explicit)] if explicit else []
    alpha = Path(os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", root.parent / "alpha_research"))
    search_roots = [
        root / "data",
        root / "output" / "strategy_factory" / "market_data",
        alpha / "data",
        alpha / "strategy_factory" / "data",
        alpha / "strategy_factory_workbench" / "workbench_data" / "market_data",
    ]
    for search_root in search_roots:
        if search_root.exists():
            candidates.extend(search_root.rglob("*.csv"))
    seen: set[str] = set()
    unique = []
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _load_price_series(path: Path) -> tuple[list[dict[str, Any]], str | None, str | None]:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return [], None, None
    if not rows:
        return [], None, None
    columns = {name.lower(): name for name in rows[0].keys()}
    date_col = columns.get("date") or columns.get("timestamp")
    if not date_col:
        return [], None, None
    symbol_col = columns.get("symbol") or columns.get("ticker")
    close_col = (
        columns.get("adj_close")
        or columns.get("adjusted_close")
        or columns.get("close")
        or columns.get("price")
    )
    if symbol_col and close_col:
        by_symbol: dict[str, dict[str, float]] = {}
        for row in rows:
            symbol = str(row.get(symbol_col) or "").upper()
            price = _float(row.get(close_col))
            date = str(row.get(date_col) or "")[:10]
            if symbol and price is not None and date:
                by_symbol.setdefault(symbol, {})[date] = price
        copper = next((symbol for symbol in COPPER_SYMBOLS if symbol in by_symbol), None)
        bench = next((symbol for symbol in BENCHMARK_SYMBOLS if symbol in by_symbol and symbol != copper), None)
        if not copper or not bench:
            return [], copper, bench
        dates = sorted(set(by_symbol[copper]).intersection(by_symbol[bench]))
        return [{"date": date, "copper": by_symbol[copper][date], "benchmark": by_symbol[bench][date]} for date in dates], copper, bench
    upper_columns = {name.upper(): name for name in rows[0].keys()}
    copper_col = next((upper_columns[symbol] for symbol in COPPER_SYMBOLS if symbol in upper_columns), None)
    bench_col = next((upper_columns[symbol] for symbol in BENCHMARK_SYMBOLS if symbol in upper_columns and upper_columns[symbol] != copper_col), None)
    if not copper_col or not bench_col:
        return [], copper_col, bench_col
    parsed = []
    for row in rows:
        copper_price = _float(row.get(copper_col))
        bench_price = _float(row.get(bench_col))
        date = str(row.get(date_col) or "")[:10]
        if copper_price is not None and bench_price is not None and date:
            parsed.append({"date": date, "copper": copper_price, "benchmark": bench_price})
    return parsed, copper_col, bench_col


def _find_market_series(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inspected = []
    for path in _market_data_candidates(root):
        inspected.append(str(path))
        if not path.is_file():
            continue
        series, copper_symbol, benchmark_symbol = _load_price_series(path)
        if len(series) >= 100 and copper_symbol and benchmark_symbol:
            return series, {"path": str(path), "copper_symbol": copper_symbol, "benchmark_symbol": benchmark_symbol}
    return [], {"inspected_paths": inspected}


def _provider_market_series(root: Path, availability: Any, requirements: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider = select_local_provider()
    usable_symbols = list(availability.usable_symbols or [])
    benchmark_symbol = availability.benchmark_symbol
    if not usable_symbols or not benchmark_symbol:
        return [], {"provider": provider.provider_name, "reason": "availability did not identify usable symbols and benchmark"}
    prices = provider.get_price_history(
        usable_symbols + [benchmark_symbol],
        requirements.get("start"),
        requirements.get("end"),
    )
    if prices.empty:
        return [], {"provider": provider.provider_name, "reason": "provider returned no rows"}
    by_symbol: dict[str, dict[str, float]] = {}
    price_col = "adj_close" if "adj_close" in prices.columns else "close"
    for _, row in prices.iterrows():
        symbol = str(row.get("symbol") or "").upper()
        date_value = row.get("date")
        price = _float(row.get(price_col))
        if not symbol or price is None:
            continue
        date = str(date_value)[:10]
        by_symbol.setdefault(symbol, {})[date] = price
    copper_symbol = next((symbol for symbol in usable_symbols if symbol in by_symbol), None)
    if not copper_symbol or benchmark_symbol not in by_symbol:
        return [], {"provider": provider.provider_name, "reason": "usable symbol or benchmark missing from provider frame"}
    dates = sorted(set(by_symbol[copper_symbol]).intersection(by_symbol[benchmark_symbol]))
    series = [{"date": date, "copper": by_symbol[copper_symbol][date], "benchmark": by_symbol[benchmark_symbol][date]} for date in dates]
    return series, {
        "provider": provider.provider_name,
        "copper_symbol": copper_symbol,
        "benchmark_symbol": benchmark_symbol,
        "data_layer_decision": availability.decision,
    }


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _max_drawdown(equity_rows: list[dict[str, Any]]) -> float:
    peak = None
    worst = 0.0
    for row in equity_rows:
        equity = float(row["strategy_equity"])
        peak = equity if peak is None else max(peak, equity)
        if peak:
            worst = min(worst, equity / peak - 1.0)
    return worst


def _monthly(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, float]] = {}
    for row in rows:
        month = str(row["date"])[:7]
        bucket = buckets.setdefault(month, {"strategy": 1.0, "benchmark": 1.0})
        bucket["strategy"] *= 1.0 + float(row["net_return"])
        bucket["benchmark"] *= 1.0 + float(row["benchmark_return"])
    return [
        {"month": month, "strategy_return": bucket["strategy"] - 1.0, "benchmark_return": bucket["benchmark"] - 1.0}
        for month, bucket in sorted(buckets.items())
    ]


def _svg_placeholder(path: Path, title: str, message: str) -> None:
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="320" viewBox="0 0 900 320">
<rect width="900" height="320" fill="#061315"/>
<text x="32" y="70" fill="#72d0f6" font-family="Arial" font-size="26">{title}</text>
<text x="32" y="130" fill="#ffd36c" font-family="Arial" font-size="18">{message[:110]}</text>
</svg>
""",
        encoding="utf-8",
    )


def _svg_line(path: Path, title: str, rows: list[dict[str, Any]], value_key: str) -> None:
    if len(rows) < 2:
        _svg_placeholder(path, title, "Chart unavailable: missing real backtest series.")
        return
    values = [float(row[value_key]) for row in rows]
    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    points = []
    for idx, row in enumerate(rows):
        x = 60 + idx * 800 / max(1, len(rows) - 1)
        y = 260 - (float(row[value_key]) - lo) * 190 / span
        points.append(f"{x:.2f},{y:.2f}")
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="320" viewBox="0 0 900 320">
<rect width="900" height="320" fill="#061315"/>
<text x="32" y="42" fill="#edf8fb" font-family="Arial" font-size="22">{title}</text>
<polyline points="{' '.join(points)}" fill="none" stroke="#19aef5" stroke-width="3"/>
<text x="60" y="292" fill="#8fa6a9" font-family="Arial" font-size="14">{rows[0]['date']} to {rows[-1]['date']}</text>
</svg>
""",
        encoding="utf-8",
    )


def _run_copper_backtest(series: list[dict[str, Any]], meta: dict[str, Any], cost_bps: float = 5.0) -> dict[str, Any]:
    prices = [float(row["copper"]) for row in series]
    bench = [float(row["benchmark"]) for row in series]
    dates = [str(row["date"]) for row in series]
    copper_rets = [0.0] + [prices[idx] / prices[idx - 1] - 1.0 for idx in range(1, len(prices))]
    benchmark_rets = [0.0] + [bench[idx] / bench[idx - 1] - 1.0 for idx in range(1, len(bench))]
    daily_rows = []
    equity_rows = []
    drawdown_rows = []
    position = 0.0
    equity = 1.0
    peak = 1.0
    for idx in range(64, len(series)):
        prev_position = position
        if idx == 64 or dates[idx][8:10] <= dates[idx - 1][8:10]:
            momentum = prices[idx - 1] / prices[idx - 64] - 1.0
            vol_window = _stdev(copper_rets[idx - 20 : idx]) * math.sqrt(252) if idx >= 84 else 0.0
            long_term_vol = _stdev(copper_rets[max(1, idx - 252) : idx]) * math.sqrt(252)
            position = 1.0 if momentum > 0.0 and (not long_term_vol or vol_window <= max(long_term_vol, 0.01)) else 0.0
        turnover = abs(position - prev_position)
        cost_drag = turnover * cost_bps / 10000.0
        gross = position * copper_rets[idx]
        net = gross - cost_drag
        equity *= 1.0 + net
        peak = max(peak, equity)
        daily_rows.append(
            {
                "date": dates[idx],
                "strategy": "CURRENT_RUN_COPPER_MOMENTUM_VOL_FILTER_V0",
                "gross_return": gross,
                "transaction_cost": cost_drag,
                "cost_drag": cost_drag,
                "net_return": net,
                "turnover": turnover,
                "benchmark_return": benchmark_rets[idx],
                "base_cost_bps_per_side": cost_bps,
                "position": position,
            }
        )
        equity_rows.append({"date": dates[idx], "strategy_equity": equity, "benchmark_equity": None})
        drawdown_rows.append({"date": dates[idx], "drawdown": equity / peak - 1.0})
    bench_equity = 1.0
    for idx, row in enumerate(daily_rows):
        bench_equity *= 1.0 + float(row["benchmark_return"])
        equity_rows[idx]["benchmark_equity"] = bench_equity
    returns = [float(row["net_return"]) for row in daily_rows]
    annual_return = equity ** (252 / max(1, len(returns))) - 1.0
    vol = _stdev(returns) * math.sqrt(252)
    metrics = {
        "sharpe": (sum(returns) / len(returns) * 252) / vol if vol else METRIC_UNAVAILABLE,
        "annual_return": annual_return,
        "max_drawdown": _max_drawdown(equity_rows),
        "volatility": vol,
        "turnover": sum(float(row["turnover"]) for row in daily_rows) / len(daily_rows) if daily_rows else 0.0,
        "benchmark": meta.get("benchmark_symbol") or "Benchmark unavailable",
        "date_range": f"{daily_rows[0]['date']} to {daily_rows[-1]['date']}" if daily_rows else METRIC_UNAVAILABLE,
        "cost_assumption": f"{cost_bps} bps per one-way turnover",
    }
    return {"daily_rows": daily_rows, "equity_rows": equity_rows, "drawdown_rows": drawdown_rows, "monthly_rows": _monthly(daily_rows), "metrics": metrics}


def _chart_data(status: str, message: str, artifacts: dict[str, str], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "source_artifact_path": artifacts.get("daily_returns") or artifacts.get("backtest_run"),
        "data_range": metrics.get("date_range", METRIC_UNAVAILABLE),
        "benchmark": metrics.get("benchmark", METRIC_UNAVAILABLE),
        "cost_assumption": metrics.get("cost_assumption", METRIC_UNAVAILABLE),
        "summary_metrics": metrics,
    }


def _downsample(points: list[dict[str, Any]], max_points: int = 750) -> list[dict[str, Any]]:
    if len(points) <= max_points:
        return points
    step = max(1, math.ceil(len(points) / max_points))
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def _rolling_sharpe(rows: list[dict[str, Any]], window: int = 63) -> list[dict[str, Any]]:
    points = []
    returns = [(str(row["date"]), float(row["net_return"])) for row in rows]
    for idx in range(window - 1, len(returns)):
        sample = [value for _, value in returns[idx - window + 1 : idx + 1]]
        stdev = _stdev(sample)
        points.append({"date": returns[idx][0], "value": (sum(sample) / len(sample) / stdev) * math.sqrt(252) if stdev else 0.0})
    return _downsample(points)


def _return_histogram(rows: list[dict[str, Any]], bins: int = 12) -> list[dict[str, Any]]:
    returns = [float(row["net_return"]) for row in rows]
    if not returns:
        return []
    lo, hi = min(returns), max(returns)
    if lo == hi:
        return [{"min": lo, "max": hi, "label": f"{lo:.4f}", "count": len(returns)}]
    width = (hi - lo) / bins
    counts = [0 for _ in range(bins)]
    for value in returns:
        idx = min(bins - 1, max(0, int((value - lo) / width)))
        counts[idx] += 1
    return [
        {"min": lo + idx * width, "max": lo + (idx + 1) * width, "label": f"{lo + idx * width:.3%} to {lo + (idx + 1) * width:.3%}", "count": count}
        for idx, count in enumerate(counts)
    ]


def _available_chart_data(result: dict[str, Any], artifacts: dict[str, str], metrics: dict[str, Any]) -> dict[str, Any]:
    equity = _downsample(
        [
            {"date": row["date"], "value": float(row["strategy_equity"])}
            for row in result["equity_rows"]
        ]
    )
    benchmark = _downsample(
        [
            {"date": row["date"], "value": float(row["benchmark_equity"])}
            for row in result["equity_rows"]
        ]
    )
    drawdown = _downsample(
        [
            {"date": row["date"], "value": float(row["drawdown"])}
            for row in result["drawdown_rows"]
        ]
    )
    turnover_rows = [
        {
            "month": row["month"],
            "average_turnover": sum(float(day["turnover"]) for day in result["daily_rows"] if str(day["date"]).startswith(row["month"])) / max(1, sum(1 for day in result["daily_rows"] if str(day["date"]).startswith(row["month"]))),
            "cost_drag": sum(float(day["cost_drag"]) for day in result["daily_rows"] if str(day["date"]).startswith(row["month"])),
        }
        for row in result["monthly_rows"]
    ]
    return {
        "status": "AVAILABLE",
        "message": "Charts generated from current-run daily_returns.csv.",
        "source_artifact_path": artifacts["daily_returns"],
        "data_range": metrics.get("date_range", METRIC_UNAVAILABLE),
        "benchmark": metrics.get("benchmark", METRIC_UNAVAILABLE),
        "cost_assumption": metrics.get("cost_assumption", METRIC_UNAVAILABLE),
        "equity_curve": {"title": "Equity Curve vs Benchmark", "series": [{"label": "Strategy net equity", "values": equity}, {"label": "Benchmark equity", "values": benchmark}]},
        "drawdown": {"title": "Strategy Drawdown", "series": [{"label": "Strategy drawdown", "values": drawdown}]},
        "rolling_sharpe": {"title": "Rolling Sharpe", "window": 63, "series": [{"label": "63D rolling Sharpe", "values": _rolling_sharpe(result["daily_rows"])}]},
        "monthly_returns": {"title": "Monthly Returns", "rows": result["monthly_rows"]},
        "return_distribution": {"title": "Return Distribution", "bins": _return_histogram(result["daily_rows"])},
        "turnover_cost": {"title": "Turnover / Transaction Cost", "rows": turnover_rows},
        "summary_metrics": metrics,
    }


def _blocked_payload(
    reason: str,
    run_manifest: dict[str, Any],
    artifacts: dict[str, str],
    testability_decision: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    theme = str(run_manifest.get("strategy_factory_theme") or "")
    backtest = {
        "schema_version": "strategy_factory_backtest_run_v0",
        "run_id": run_manifest.get("run_id"),
        "batch_id": run_manifest.get("batch_id"),
        "status": "BLOCKED",
        "reason": reason,
        "theme": theme,
        "required_data": "theme-specific daily price series and benchmark",
        "testability_decision": testability_decision,
        "selected_material_ids": run_manifest.get("selected_material_ids", []),
        "test_spec_path": artifacts.get("test_spec"),
        "generated_at": _now(),
    }
    metrics = {
        "schema_version": "strategy_factory_metrics_v0",
        "status": "BLOCKED",
        "metrics_available": False,
        "reason": reason,
    }
    ml = {
        "schema_version": "strategy_factory_ml_diagnostics_run_v0",
        "run_id": run_manifest.get("run_id"),
        "status": "BLOCKED",
        "ml_evidence_status": "MISSING_EVIDENCE",
        "reason": "Backtest did not produce a candidate-specific return series.",
        "feature_importance_available": False,
        "generated_at": _now(),
    }
    return backtest, metrics, ml


def _update_current_run_candidate(root: Path, run_manifest_path: Path, candidate_updates: dict[str, Any]) -> None:
    state = _read_json(_state_path(root), {})
    run_manifest = _read_json(run_manifest_path, {})
    candidate_path = Path(str(run_manifest.get("generated_artifacts", {}).get("current_run_candidate") or ""))
    candidates = state.get("scoped_run_candidates") if isinstance(state.get("scoped_run_candidates"), list) else []
    strategy_id = str(run_manifest.get("candidate_output", {}).get("strategy_id") or "")
    updated_candidate = None
    if candidate_path.is_file():
        candidate = _read_json(candidate_path, {})
        source_update = candidate_updates.pop("source_evidence", {})
        report_update = candidate_updates.pop("report_sections", {})
        completed_update = candidate_updates.pop("completed_stages", None)
        candidate.update(candidate_updates)
        if report_update:
            candidate["report_sections"] = {**(candidate.get("report_sections") or {}), **report_update}
        if completed_update is not None:
            candidate["completed_stages"] = completed_update
        current_run = candidate.setdefault("current_run", {})
        current_run.setdefault("generated_artifacts", {}).update(run_manifest.get("generated_artifacts", {}))
        source_evidence = candidate.setdefault("source_evidence", {})
        source_evidence.setdefault("artifact_chain", {}).update(source_update.get("artifact_chain", {}))
        _write_json(candidate_path, candidate)
        updated_candidate = candidate
    if updated_candidate and strategy_id:
        state["scoped_run_candidates"] = [
            updated_candidate if row.get("strategy_id") == strategy_id else row
            for row in candidates
        ]
    latest = state.get("latest_run") if isinstance(state.get("latest_run"), dict) else {}
    if latest.get("run_id") == run_manifest.get("run_id"):
        latest["stage"] = candidate_updates.get("pipeline_stage", latest.get("stage"))
        latest["generated_artifacts"] = run_manifest.get("generated_artifacts", {})
        state["latest_run"] = latest
    state["last_status_message"] = candidate_updates.get("next_action") or state.get("last_status_message")
    _write_json(_state_path(root), state)


def run_current_backtest_ml(root: Path, run_id: str | None = None) -> dict[str, Any]:
    manifest_path = _latest_run_manifest_path(root)
    if run_id:
        candidate = _factory_root(root) / "runs" / run_id / "run_manifest.json"
        manifest_path = candidate if candidate.is_file() else manifest_path
    if manifest_path is None or not manifest_path.is_file():
        raise ValueError("No current Strategy Factory run_manifest.json found. Run Selected Batch first.")

    run_manifest = _read_json(manifest_path, {})
    run_dir = manifest_path.parent
    spec_text, spec_path = _selected_test_spec_text(run_manifest)
    artifacts = {
        "test_spec": spec_path,
        "backtest_run": str(run_dir / "backtest_run.json"),
        "metrics": str(run_dir / "metrics.json"),
        "daily_returns": str(run_dir / "daily_returns.csv"),
        "equity_curve": str(run_dir / "equity_curve.csv"),
        "equity_curve_svg": str(run_dir / "equity_curve.svg"),
        "drawdown": str(run_dir / "drawdown.csv"),
        "drawdown_svg": str(run_dir / "drawdown.svg"),
        "monthly_returns": str(run_dir / "monthly_returns.csv"),
        "monthly_returns_table": str(run_dir / "monthly_returns_table.md"),
        "ml_diagnostics_run": str(run_dir / "ml_diagnostics_run.json"),
        "feature_importance_csv": str(run_dir / "feature_importance.csv"),
        "feature_importance_json": str(run_dir / "feature_importance.json"),
        "prediction_quality": str(run_dir / "prediction_quality.json"),
        "train_test_split": str(run_dir / "train_test_split.json"),
        "leakage_check": str(run_dir / "leakage_check.json"),
        "evidence_report": str(run_dir / "evidence_report.md"),
        **{key: str(run_dir / filename) for key, filename in INTELLIGENCE_ARTIFACT_KEYS.items()},
    }
    text = _run_text(run_manifest)
    provider = select_local_provider()
    proxy_mapping = load_proxy_mapping(getattr(provider, "root", None))
    data_requirements = infer_data_requirements(run_manifest, text)
    theme = str(data_requirements.get("theme") or THEME_UNKNOWN_REVIEW_REQUIRED)
    run_manifest["strategy_factory_theme"] = theme
    data_availability = evaluate_availability(provider, data_requirements, proxy_mapping)
    artifacts.update(write_run_data_artifacts(run_dir, data_requirements, data_availability, proxy_mapping))
    reason = ""
    result: dict[str, Any] | None = None
    series_meta: dict[str, Any] = {}
    if not spec_text.strip():
        reason = "No current-run test spec artifact is available."
    elif theme == THEME_ETF_MOMENTUM_ROTATION:
        reason = "DATA_MISSING: current-run ETF backtest dispatch is handled by Gate 3 variant evaluation; no ETF ML evidence is available in the copper V0 current-run runner."
    elif theme == THEME_US_STOCK_MOMENTUM_QUALITY:
        reason = "DATA_MISSING: current-run U.S. stock cross-sectional evidence is handled by Gate 3 variant evaluation; no U.S. stock ML evidence is available in the copper V0 current-run runner."
    elif theme == THEME_UNKNOWN_REVIEW_REQUIRED:
        reason = "REVIEW_REQUIRED: unknown material does not default to copper."
    elif theme != THEME_COMMODITY_PROXY_TREND:
        reason = f"REVIEW_REQUIRED: unsupported Strategy Factory theme {theme}."
    elif data_availability.decision not in {DECISION_READY, DECISION_PROXY_ONLY}:
        reason = f"{data_availability.decision}: {data_availability.reason}"
    else:
        series, series_meta = _provider_market_series(root, data_availability, data_requirements)
        if not series:
            reason = "No local candidate-specific copper/proxy and benchmark daily price series was found through the data provider."
        elif len(series) < 100:
            reason = f"Only {len(series)} overlapping provider observations were found; at least 100 are required."
        else:
            result = _run_copper_backtest(series, series_meta)

    if result is None:
        backtest, metrics, ml = _blocked_payload(reason, run_manifest, artifacts, data_availability.decision)
        _write_json(Path(artifacts["backtest_run"]), backtest)
        _write_json(Path(artifacts["metrics"]), metrics)
        _write_csv(Path(artifacts["daily_returns"]), ["date", "strategy", "gross_return", "transaction_cost", "cost_drag", "net_return", "turnover", "benchmark_return", "base_cost_bps_per_side"], [])
        _write_csv(Path(artifacts["equity_curve"]), ["date", "strategy_equity", "benchmark_equity"], [])
        _write_csv(Path(artifacts["drawdown"]), ["date", "drawdown"], [])
        _write_csv(Path(artifacts["monthly_returns"]), ["month", "strategy_return", "benchmark_return"], [])
        Path(artifacts["monthly_returns_table"]).write_text("| Month | Strategy | Benchmark |\n|---|---:|---:|\n", encoding="utf-8")
        _write_json(Path(artifacts["ml_diagnostics_run"]), ml)
        _write_csv(Path(artifacts["feature_importance_csv"]), ["feature", "importance", "status"], [])
        _write_json(Path(artifacts["feature_importance_json"]), {"status": "BLOCKED", "feature_importance": [], "reason": ml["reason"]})
        _write_json(Path(artifacts["prediction_quality"]), {"schema_version": "strategy_factory_prediction_quality_v0", "status": "BLOCKED", "reason": ml["reason"], "metrics": {}})
        _write_json(Path(artifacts["train_test_split"]), {"schema_version": "strategy_factory_train_test_split_v0", "status": "BLOCKED", "reason": ml["reason"], "split_method": "chronological_no_shuffle"})
        _write_json(Path(artifacts["leakage_check"]), {"schema_version": "strategy_factory_leakage_check_v0", "status": "BLOCKED", "reason": ml["reason"]})
        _svg_placeholder(Path(artifacts["equity_curve_svg"]), "Equity Curve", reason)
        _svg_placeholder(Path(artifacts["drawdown_svg"]), "Drawdown", reason)
        chart_data = _chart_data("BLOCKED", "Chart unavailable: missing real backtest series.", artifacts, {})
        pipeline_stage = "BACKTEST_BLOCKED"
    else:
        metrics = result["metrics"]
        backtest = {
            "schema_version": "strategy_factory_backtest_run_v0",
            "run_id": run_manifest.get("run_id"),
            "batch_id": run_manifest.get("batch_id"),
            "status": "COMPLETED",
            "theme": theme,
            "strategy_id": run_manifest.get("candidate_output", {}).get("strategy_id"),
            "strategy_name": "Current Run Copper Momentum Volatility Filter V0",
            "testability_decision": data_availability.decision,
            "prototype_proxy_only": data_availability.decision == DECISION_PROXY_ONLY,
            "benchmark": metrics["benchmark"],
            "universe": series_meta.get("copper_symbol"),
            "test_period": {"start_date": result["daily_rows"][0]["date"], "end_date": result["daily_rows"][-1]["date"]},
            "cost_assumptions": {"transaction_cost_bps": 5.0},
            "key_metrics": {
                "sharpe": metrics["sharpe"],
                "annualized_return": metrics["annual_return"],
                "max_drawdown": metrics["max_drawdown"],
                "annualized_volatility": metrics["volatility"],
                "average_turnover": metrics["turnover"],
            },
            "source_price_artifact": series_meta.get("path"),
            "source_provider": series_meta.get("provider"),
            "generated_at": _now(),
        }
        _write_json(Path(artifacts["backtest_run"]), backtest)
        _write_json(Path(artifacts["metrics"]), {"schema_version": "strategy_factory_metrics_v0", "status": "COMPLETED", **metrics})
        _write_csv(Path(artifacts["daily_returns"]), ["date", "strategy", "gross_return", "transaction_cost", "cost_drag", "net_return", "turnover", "benchmark_return", "base_cost_bps_per_side", "position"], result["daily_rows"])
        _write_csv(Path(artifacts["equity_curve"]), ["date", "strategy_equity", "benchmark_equity"], result["equity_rows"])
        _write_csv(Path(artifacts["drawdown"]), ["date", "drawdown"], result["drawdown_rows"])
        _write_csv(Path(artifacts["monthly_returns"]), ["month", "strategy_return", "benchmark_return"], result["monthly_rows"])
        Path(artifacts["monthly_returns_table"]).write_text(
            "| Month | Strategy | Benchmark |\n|---|---:|---:|\n"
            + "\n".join(f"| {row['month']} | {row['strategy_return']:.4%} | {row['benchmark_return']:.4%} |" for row in result["monthly_rows"])
            + "\n",
            encoding="utf-8",
        )
        _svg_line(Path(artifacts["equity_curve_svg"]), "Equity Curve vs Benchmark", result["equity_rows"], "strategy_equity")
        _svg_line(Path(artifacts["drawdown_svg"]), "Strategy Drawdown", result["drawdown_rows"], "drawdown")
        ml = run_current_run_ml_diagnostics(run_dir, artifacts, backtest, metrics)
        chart_data = _available_chart_data(result, artifacts, metrics)
        pipeline_stage = "BACKTEST_RUN"

    write_evidence_report(Path(artifacts["evidence_report"]), run_manifest, artifacts, backtest, metrics, ml)
    intelligence = run_current_run_intelligence(run_dir, artifacts)

    run_manifest["status"] = "BACKTEST_BLOCKED" if backtest["status"] == "BLOCKED" else "BACKTEST_COMPLETED"
    run_manifest["updated_at"] = _now()
    run_manifest.setdefault("generated_artifacts", {}).update(artifacts)
    run_manifest["backtest_status"] = backtest["status"]
    run_manifest["ml_status"] = ml["status"]
    run_manifest["intelligence_status"] = intelligence["status"]
    run_manifest["testability_decision"] = data_availability.decision
    if backtest["status"] == "BLOCKED":
        run_manifest.setdefault("errors", []).append({"stage": "BACKTEST_RUN", "reason": reason, "timestamp": _now()})
    _write_json(manifest_path, run_manifest)

    candidate_updates = {
        "pipeline_stage": pipeline_stage,
        "backtest_status": backtest["status"],
        "ml_result_summary": f"ML_DIAGNOSTICS_RUN: {ml['status']}",
        "ml_model_used": ml.get("model"),
        "recommendation": intelligence.get("recommendation") or ml.get("recommendation"),
        "intelligence_status": intelligence.get("status"),
        "strategy_type": intelligence.get("strategy_type"),
        "theme": theme,
        "intelligence_report_path": artifacts["intelligence_report"],
        "chart_data": chart_data,
        "report_path": artifacts["evidence_report"],
        "evidence_report_path": artifacts["evidence_report"],
        "report_sections": {
            "Executive Summary": f"Current run backtest status: {backtest['status']}. Data decision: {data_availability.decision}. Recommendation: {ml.get('recommendation', 'Unavailable')}.",
            "Backtest Methodology": "Theme-dispatched prototype runner reads current-run test_spec and local market data only.",
            "ML Diagnostics": f"ML status: {ml['status']}; model: {ml.get('model', 'Unavailable')}.",
            "Feature Importance": _read_json(Path(artifacts["feature_importance_json"]), {}).get("feature_importance", []),
            "Intelligence": f"Strategy type: {intelligence.get('strategy_type')}; recommendation: {intelligence.get('recommendation')}.",
            "Limitations": backtest.get("reason") or f"Research-only prototype backtest; data decision {data_availability.decision}; not an admission decision.",
            "Next Action": "Provide local price series if blocked; otherwise review generated artifacts.",
        },
        "source_evidence": {"artifact_chain": {"backtest": artifacts["backtest_run"], "ml_diagnostics": artifacts["ml_diagnostics_run"], "feature_importance": artifacts["feature_importance_json"], "prediction_quality": artifacts["prediction_quality"], "train_test_split": artifacts["train_test_split"], "leakage_check": artifacts["leakage_check"], "evidence": artifacts["evidence_report"], "data_availability": artifacts["data_availability"], "testability_decision": artifacts["testability_decision"], "intelligence_plan": artifacts["intelligence_plan"], "strategy_type_classification": artifacts["strategy_type_classification"], "feature_plan": artifacts["feature_plan"], "model_plan": artifacts["model_plan"], "robustness_plan": artifacts["robustness_plan"], "robustness_run": artifacts["robustness_run"], "lookback_sensitivity": artifacts["lookback_sensitivity_json"], "cost_sensitivity": artifacts["cost_sensitivity_json"], "rebalance_sensitivity": artifacts["rebalance_sensitivity_json"], "benchmark_comparison": artifacts["benchmark_comparison_json"], "stress_period_summary": artifacts["stress_period_summary"], "ml_lift_vs_rule_signal": artifacts["ml_lift_vs_rule_signal"], "robustness_report": artifacts["robustness_report"], "validation_scorecard": artifacts["validation_scorecard"], "decision_scorecard": artifacts["decision_scorecard"], "intelligence_report": artifacts["intelligence_report"]}},
        "next_action": "Backtest/ML artifacts generated locally." if backtest["status"] == "COMPLETED" else f"BACKTEST_RUN BLOCKED: {reason}",
        "testability_decision": data_availability.decision,
    }
    if backtest["status"] == "COMPLETED":
        completed_stages = ["MATERIALS_UPLOADED", "EXTRACTED", "MATERIALS_ANALYZED", "CANDIDATE_IDEAS_GENERATED", "RESEARCH_CARD_CREATED", "TEST_SPEC_CREATED", "BACKTEST_RUN"]
        if ml.get("status") == "COMPLETED":
            completed_stages.append("ML_DIAGNOSTICS_RUN")
        completed_stages.append("EVIDENCE_REPORT_CREATED")
        candidate_updates.update(
            {
                "completed_stages": completed_stages,
                "backtest_metrics": metrics,
                "benchmark": metrics.get("benchmark", METRIC_UNAVAILABLE),
                "date_range": metrics.get("date_range", METRIC_UNAVAILABLE),
                "cost_assumption": metrics.get("cost_assumption", METRIC_UNAVAILABLE),
                "ml_diagnostics": {**ml, "feature_importance": _read_json(Path(artifacts["feature_importance_json"]), {}).get("feature_importance", [])},
                "decision_status": f"{(intelligence.get('recommendation') or ml.get('recommendation', 'Watch')).upper()} / RESEARCH_ONLY / REVIEW_REQUIRED",
                "testability_decision": data_availability.decision,
            }
        )
    else:
        candidate_updates.update({"completed_stages": ["MATERIALS_UPLOADED", "EXTRACTED", "MATERIALS_ANALYZED", "CANDIDATE_IDEAS_GENERATED", "RESEARCH_CARD_CREATED", "TEST_SPEC_CREATED"], "backtest_metrics": {}, "testability_decision": data_availability.decision})
    _update_current_run_candidate(root, manifest_path, candidate_updates)
    return {"ok": True, "run_id": run_manifest.get("run_id"), "status": backtest["status"], "reason": backtest.get("reason"), "artifacts": artifacts, "backtest": backtest, "ml_diagnostics": ml, "intelligence": intelligence}


def _append_run_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _job_stage(name: str, status: str, reason: str = "", artifact_path: str | None = None) -> dict[str, Any]:
    return {
        "stage": name,
        "status": status,
        "reason": reason or ("Completed." if status == "COMPLETED" else ""),
        "artifact_path": artifact_path,
        "updated_at": _now(),
    }


def _read_stage_json(path: str | None) -> dict[str, Any]:
    return _read_json(Path(str(path or "")), {}) if path else {}


def _full_pipeline_stages(result: dict[str, Any], artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    availability = _read_stage_json(artifacts.get("data_availability"))
    decision = _read_stage_json(artifacts.get("testability_decision"))
    backtest = result.get("backtest") if isinstance(result.get("backtest"), dict) else _read_stage_json(artifacts.get("backtest_run"))
    ml = result.get("ml_diagnostics") if isinstance(result.get("ml_diagnostics"), dict) else _read_stage_json(artifacts.get("ml_diagnostics_run"))
    evidence_path = Path(str(artifacts.get("evidence_report") or ""))

    data_decision = str(decision.get("decision") or availability.get("decision") or "").upper()
    data_status = "COMPLETED" if data_decision in {DECISION_READY, DECISION_PROXY_ONLY} else "BLOCKED"
    stages = [
        _job_stage(
            "DATA_AVAILABILITY_CHECK",
            data_status,
            decision.get("reason") or availability.get("reason") or data_decision or "Data availability artifact missing.",
            artifacts.get("data_availability"),
        )
    ]

    backtest_status = str(backtest.get("status") or "BLOCKED")
    stages.append(
        _job_stage(
            "BACKTEST_CURRENT_RUN",
            backtest_status,
            backtest.get("reason") or ("Backtest produced metrics.json." if backtest_status == "COMPLETED" else "Backtest artifact did not complete."),
            artifacts.get("backtest_run"),
        )
    )

    ml_status = str(ml.get("status") or "BLOCKED")
    stages.append(
        _job_stage(
            "ML_DIAGNOSTICS",
            ml_status,
            ml.get("reason") or ("ML diagnostics artifact exists." if ml_status == "COMPLETED" else "ML diagnostics artifact is blocked or missing."),
            artifacts.get("ml_diagnostics_run"),
        )
    )

    if evidence_path.is_file():
        evidence_status = "COMPLETED" if backtest_status == "COMPLETED" and ml_status == "COMPLETED" else "COMPLETED_WITH_BLOCKED_INPUTS"
        evidence_reason = "Evidence report generated from available current-run artifacts."
    else:
        evidence_status = "BLOCKED"
        evidence_reason = "evidence_report.md was not generated."
    stages.append(_job_stage("EVIDENCE_REPORT", evidence_status, evidence_reason, str(evidence_path) if evidence_path else None))
    intelligence = result.get("intelligence") if isinstance(result.get("intelligence"), dict) else {}
    intelligence_path = artifacts.get("intelligence_report")
    if intelligence.get("status") == "COMPLETED":
        stages.append(_job_stage("INTELLIGENCE_REPORT", "COMPLETED", "Intelligence scorecards and report generated.", intelligence_path))
    elif intelligence_path and Path(str(intelligence_path)).is_file():
        stages.append(_job_stage("INTELLIGENCE_REPORT", "COMPLETED_WITH_BLOCKED_INPUTS", "Intelligence artifacts exist but upstream evidence has blockers.", intelligence_path))
    else:
        stages.append(_job_stage("INTELLIGENCE_REPORT", "BLOCKED", "Intelligence report was not generated.", intelligence_path))
    return stages


def _full_pipeline_status(stages: list[dict[str, Any]]) -> tuple[str, str | None]:
    blocked = [stage for stage in stages if stage.get("status") == "BLOCKED"]
    if blocked:
        first = blocked[0]
        return "BLOCKED", f"{first.get('stage')}: {first.get('reason')}"
    blockers = [stage for stage in stages if stage.get("status") == "COMPLETED_WITH_BLOCKED_INPUTS"]
    if blockers:
        return "COMPLETED_WITH_BLOCKERS", blockers[0].get("reason")
    return "COMPLETED", None


def run_full_current_run_job(root: Path, run_id: str | None = None) -> dict[str, Any]:
    manifest_path = _latest_run_manifest_path(root)
    if run_id:
        candidate = _factory_root(root) / "runs" / run_id / "run_manifest.json"
        manifest_path = candidate if candidate.is_file() else manifest_path
    if manifest_path is None or not manifest_path.is_file():
        raise ValueError("No current Strategy Factory run_manifest.json found. Run Selected Batch first.")

    run_manifest = _read_json(manifest_path, {})
    run_dir = manifest_path.parent
    job_path = run_dir / "job_status.json"
    log_path = run_dir / "run_log.txt"
    started_at = _now()
    running_job = {
        "schema_version": "strategy_factory_full_current_run_job_v0",
        "job_name": "run-full-current-run",
        "run_id": run_manifest.get("run_id"),
        "status": "RUNNING",
        "started_at": started_at,
        "completed_at": None,
        "stages": [
            _job_stage("DATA_AVAILABILITY_CHECK", "RUNNING", "Checking local provider availability.", None),
            _job_stage("BACKTEST_CURRENT_RUN", "QUEUED", "Waiting for data availability.", None),
            _job_stage("ML_DIAGNOSTICS", "QUEUED", "Waiting for backtest artifact.", None),
            _job_stage("EVIDENCE_REPORT", "QUEUED", "Waiting for metrics and diagnostics artifacts.", None),
        ],
        "artifacts": {"job_status": str(job_path), "run_log": str(log_path)},
    }
    _write_json(job_path, running_job)
    _append_run_log(log_path, f"START run-full-current-run run_id={run_manifest.get('run_id')}")

    try:
        result = run_current_backtest_ml(root, run_id=run_manifest.get("run_id"))
        artifacts = {**(result.get("artifacts") or {}), "job_status": str(job_path), "run_log": str(log_path)}
        stages = _full_pipeline_stages(result, artifacts)
        status, reason = _full_pipeline_status(stages)
        ml = result.get("ml_diagnostics") if isinstance(result.get("ml_diagnostics"), dict) else {}
        intelligence = result.get("intelligence") if isinstance(result.get("intelligence"), dict) else {}
        job = {
            "schema_version": "strategy_factory_full_current_run_job_v0",
            "job_name": "run-full-current-run",
            "run_id": run_manifest.get("run_id"),
            "status": status,
            "reason": reason,
            "started_at": started_at,
            "completed_at": _now(),
            "stages": stages,
            "artifacts": artifacts,
            "recommendation": intelligence.get("recommendation") or ml.get("recommendation"),
        }
        _write_json(job_path, job)
        _append_run_log(log_path, f"FINISH run-full-current-run status={status} reason={reason or 'none'}")

        updated_manifest = _read_json(manifest_path, {})
        updated_manifest.setdefault("generated_artifacts", {}).update({"job_status": str(job_path), "run_log": str(log_path)})
        updated_manifest["full_pipeline_status"] = status
        updated_manifest["updated_at"] = _now()
        _write_json(manifest_path, updated_manifest)

        _update_current_run_candidate(
            root,
            manifest_path,
            {
                "full_pipeline_status": status,
                "full_pipeline_reason": reason,
                "full_pipeline_stages": stages,
                "full_pipeline_job_status_path": str(job_path),
                "run_log_path": str(log_path),
                "recommendation": intelligence.get("recommendation") or ml.get("recommendation"),
                "source_evidence": {"artifact_chain": {"job_status": str(job_path), "run_log": str(log_path)}},
                "next_action": "Full current-run pipeline completed." if status == "COMPLETED" else f"Full pipeline {status}: {reason}",
            },
        )
        return {"ok": True, **job, "backtest": result.get("backtest"), "ml_diagnostics": result.get("ml_diagnostics")}
    except Exception as exc:
        job = {
            **running_job,
            "status": "FAILED",
            "reason": str(exc),
            "completed_at": _now(),
            "stages": [
                stage if stage["status"] not in {"RUNNING", "QUEUED"} else {**stage, "status": "FAILED", "reason": str(exc), "updated_at": _now()}
                for stage in running_job["stages"]
            ],
        }
        _write_json(job_path, job)
        _append_run_log(log_path, f"FAILED run-full-current-run reason={exc}")
        raise
