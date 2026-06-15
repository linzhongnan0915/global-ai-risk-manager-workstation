"""Generate dashboard JSON artifacts from sample configs."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from src.allocation.optimizer import propose_allocation
from src.allocation.rebalance_simulation import build_simulation_context
from src.portfolio.return_alignment import (
    align_strategy_series,
    align_strategy_series_for_weights,
    series_map_from_literature_results,
    slice_aligned_window,
    weighted_portfolio_series,
)
from src.governance.decision_workflow import build_decision_workflow
from src.market.api_client import load_market_snapshot, summarize_market_risk
from src.news.news_analyzer import analyze_news_risk, load_news_snapshot
from src.portfolio.ledger import validate_weights
from src.risk.performance import max_drawdown, sharpe_ratio, volatility
from src.risk.recommendation_engine import build_recommendations
from src.risk.engine import portfolio_risk_summary
from src.risk.correlation import strategy_correlation_report
from src.risk.decision_engine import review_decisions
from src.risk.limits import (
    evaluate_correlation_limits,
    evaluate_evidence_limits,
    evaluate_factor_limits,
    evaluate_portfolio_limits,
    evaluate_portfolio_limits_with_availability,
    evaluate_rebalance_limits,
    evaluate_research_quality_limits,
    evaluate_residual_cash_limit,
    evaluate_scenario_limits,
    evaluate_strategy_limits,
    load_risk_limits,
    summarize_limit_status,
    worst_status,
)
from src.risk.metric_availability import build_operating_period_risk, wrap_metric, load_metric_availability
from src.risk.risk_status_summary import build_risk_status_summary, decorate_strategy_status_fields, enrich_check
from src.risk.transaction_cost import TransactionCostModel
from src.strategies.registry import load_strategy_registry

ARTIFACT_SCHEMA_VERSION = "0.3.0"


def _load_literature_modules(path: str | Path = "data/config/literature_modules.json") -> list[dict]:
    module_path = Path(path)
    if not module_path.exists():
        return []
    with module_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return list(payload.get("modules", []))


def _load_replication_snapshot(path: str | Path = "output/replication_clone_snapshot.json") -> dict:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return {}
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def _load_literature_strategy_backtests(path: str | Path = "output/literature_strategy_backtests.json") -> dict:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return {}
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def _load_workstation_ui_contract(path: str | Path = "data/config/workstation_ui_contract.json") -> dict:
    contract_path = Path(path)
    if not contract_path.exists():
        return {}
    return json.loads(contract_path.read_text(encoding="utf-8"))


def _literature_result_rows(payload: dict) -> list[dict]:
    rows = []
    for item in payload.get("results", []):
        if "backtest" in item:
            rows.append(item)
    return rows


def _aligned_window_from_literature(results: list[dict], weights: dict[str, float] | None = None):
    series_map = series_map_from_literature_results(results)
    if weights is not None:
        return align_strategy_series_for_weights(series_map, weights)
    strategy_ids = [item["backtest"]["strategy_id"] for item in results]
    return align_strategy_series(series_map, strategy_ids)


def _strategy_returns_from_literature(results: list[dict]) -> dict[str, list[float]]:
    return _aligned_window_from_literature(results).as_dict()


def _portfolio_chart_series_from_literature(results: list[dict], weights: dict[str, float]) -> dict:
    aligned = _aligned_window_from_literature(results, weights)
    return weighted_portfolio_series(aligned, weights)


def _sample_returns(strategy_ids: list[str], periods: int = 64) -> dict[str, list[float]]:
    returns = {}
    for idx, strategy_id in enumerate(strategy_ids, start=1):
        base = 0.00025 + (idx % 5) * 0.00003
        wave = []
        for day in range(periods):
            shock = ((day * (idx + 3)) % 11 - 5) * 0.00035
            wave.append(base + shock)
        returns[strategy_id] = wave
    return returns


def _strategy_proxy_returns_from_prices(strategies, periods: int = 64) -> dict[str, list[float]]:
    price_path = Path("data/processed/market_price_history.csv")
    if not price_path.exists():
        return _sample_returns([record.strategy_id for record in strategies], periods)

    panel = pd.read_csv(price_path)
    if panel.empty or not {"date", "ticker", "adj_close"}.issubset(panel.columns):
        return _sample_returns([record.strategy_id for record in strategies], periods)

    panel["date"] = pd.to_datetime(panel["date"])
    prices = panel.pivot_table(index="date", columns="ticker", values="adj_close", aggfunc="last").sort_index()
    returns = prices.pct_change(fill_method=None).dropna(how="all")
    output: dict[str, list[float]] = {}
    fallback = _sample_returns([record.strategy_id for record in strategies], periods)

    for record in strategies:
        raw_universe = record.raw.get("proxy_universe") or record.raw.get("universe", [])
        tickers = [str(ticker).replace("^VIX", "VIX") for ticker in raw_universe]
        usable = [ticker for ticker in tickers if ticker in returns.columns]
        if not usable:
            output[record.strategy_id] = fallback[record.strategy_id]
            continue
        series = returns[usable].mean(axis=1, skipna=True).dropna().tail(periods)
        if series.empty:
            output[record.strategy_id] = fallback[record.strategy_id]
        else:
            output[record.strategy_id] = [float(value) for value in series]

    min_len = min(len(values) for values in output.values())
    if min_len <= 0:
        return fallback
    return {key: values[-min_len:] for key, values in output.items()}


def _strategy_proxy_metrics(strategy_returns: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    metrics = {}
    for strategy_id, returns in strategy_returns.items():
        metrics[strategy_id] = {
            "daily_return": float(returns[-1]),
            "proxy_sharpe": sharpe_ratio(returns),
            "proxy_volatility": volatility(returns),
            "proxy_max_drawdown": max_drawdown(returns),
        }
    return metrics


def _portfolio_chart_series(strategy_returns: dict[str, list[float]], weights: dict[str, float]) -> dict:
    if not strategy_returns:
        return {"dates": [], "returns": [], "cumulative_return": [], "drawdown": []}
    min_len = min(len(values) for values in strategy_returns.values() if values)
    if min_len <= 0:
        return {"dates": [], "returns": [], "cumulative_return": [], "drawdown": []}
    weighted = []
    for idx in range(-min_len, 0):
        daily = 0.0
        for strategy_id, returns in strategy_returns.items():
            daily += float(weights.get(strategy_id, 0.0)) * float(returns[idx])
        weighted.append(daily)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=min_len)
    wealth = pd.Series(1.0 + pd.Series(weighted)).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    return {
        "dates": [value.date().isoformat() for value in dates],
        "returns": [float(value) for value in weighted],
        "cumulative_return": [float(value - 1.0) for value in wealth],
        "drawdown": [float(value) for value in drawdown],
    }


def _available_price_tickers() -> set[str]:
    price_path = Path("data/processed/market_price_history.csv")
    if not price_path.exists():
        return set()
    panel = pd.read_csv(price_path, usecols=["ticker"])
    return set(str(ticker) for ticker in panel["ticker"].dropna().unique())


def _equal_weights(strategy_ids: list[str]) -> dict[str, float]:
    if not strategy_ids:
        return {}
    weight = 1.0 / len(strategy_ids)
    return {strategy_id: weight for strategy_id in strategy_ids}


def _load_investment_start(path: str | Path = "data/config/dashboard_artifact_contract.json") -> str:
    contract_path = Path(path)
    if not contract_path.exists():
        return "2026-06-04"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    return str(payload.get("metadata", {}).get("start_date", "2026-06-04"))


def _research_quality_label(status: str) -> str:
    if status == "breach":
        return "fail"
    if status in {"watch", "warning"}:
        return "watch"
    return "pass"


def _artifact_build_metadata(
    *,
    market_as_of: str | None,
    operating_period_start: str,
    operating_period_end: str | None,
) -> dict:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    build_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "build_id": f"p0a-{build_stamp}",
        "artifact_generated_at": generated_at,
        "market_as_of": market_as_of,
        "operating_period_start": operating_period_start,
        "operating_period_end": operating_period_end,
        "data_retrieved_at": generated_at,
    }


def _data_classification(*, market_as_of: str | None, retrieved_at: str) -> dict:
    return {
        "portfolio_mode": "prototype_model_portfolio",
        "allocation_source": "system_generated_research_eligible_equal_weight",
        "is_live_portfolio_data": False,
        "market_data_mode": "research_market_proxy",
        "market_data_provider": "yfinance",
        "performance_source": "historical_etf_proxy_backtest",
        "operating_period_source": "historical_backtest_slice",
        "market_as_of": market_as_of,
        "retrieved_at": retrieved_at,
        "disclosure": "Prototype model portfolio · ETF proxy research data · Not live positions or fills",
    }


def _cash_semantics(current_exposure: dict[str, float], invested_weight: float) -> dict:
    residual = float(max(0.0, 1.0 - invested_weight))
    tbill = float(current_exposure.get("cash", 0.0))
    return {
        "treasury_bill_proxy_exposure": tbill,
        "portfolio_residual_cash_weight": residual,
        "treasury_bill_proxy_factor_key": "cash",
        "treasury_bill_proxy_display_label": "Treasury-bill / liquidity proxy exposure",
        "residual_cash_display_label": "Unallocated residual cash",
        "note": (
            "Treasury-bill proxy exposure is signed BIL sleeve exposure inside ETF proxy "
            "strategies. Residual cash is uninvested portfolio weight (1 - sum(weights))."
        ),
    }


def _returns_since_date(backtest: dict, start_date: str) -> list[float]:
    series = backtest.get("return_series", {})
    dates = series.get("dates", [])
    returns = series.get("net_returns", [])
    return [
        float(value)
        for day, value in zip(dates, returns)
        if day >= start_date and value is not None
    ]


def _since_investment_metrics(
    backtest: dict,
    start_date: str,
    weight: float,
    capital: float,
) -> dict:
    returns = _returns_since_date(backtest, start_date)
    if not returns:
        return {
            "start_date": start_date,
            "observations": 0,
            "cumulative_return": 0.0,
            "cumulative_pnl": 0.0,
            "sharpe": None,
            "volatility": None,
            "max_drawdown": None,
        }
    wealth = pd.Series(1.0 + pd.Series(returns)).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    allocation_dollars = float(weight * capital)
    cumulative_return = float(wealth.iloc[-1] - 1.0)
    obs = len(returns)
    metric_config = load_metric_availability()
    return {
        "start_date": start_date,
        "observations": obs,
        "cumulative_return": cumulative_return,
        "cumulative_pnl": float(cumulative_return * allocation_dollars),
        "sharpe": wrap_metric(float(sharpe_ratio(returns)) if obs >= 2 else None, "sharpe", obs, metric_config),
        "volatility": wrap_metric(float(volatility(returns)) if obs >= 2 else None, "annualized_volatility", obs, metric_config),
        "max_drawdown": wrap_metric(float(drawdown.min()), "max_drawdown", obs, metric_config),
        "current_drawdown": float(drawdown.iloc[-1]),
    }


def _score_literature_strategy(item: dict, duplicate_gate: dict | None = None) -> float:
    backtest = item["backtest"]
    net = backtest.get("net_metrics", {})
    action = backtest.get("action", {}).get("action", "")
    wfo = item.get("walk_forward", {})
    sharpe = float(net.get("sharpe", 0.0))
    max_dd = abs(float(net.get("max_drawdown", 0.0)))
    positive_window_rate = float(wfo.get("positive_window_rate", 0.0))
    average_oos_sharpe = float(wfo.get("average_test_sharpe", 0.0))
    avg_corr = float(
        backtest.get("risk_packet", {})
        .get("comparison_vs_other_strategies", {})
        .get("average_abs_correlation_to_others", 0.0)
    )
    if duplicate_gate and duplicate_gate.get("allocation_blocker"):
        return 0.0
    quality = _research_quality_for_item(item)
    if quality["eligible"] is False:
        return 0.0
    base = max(sharpe, 0.0) + 0.35 * max(average_oos_sharpe, 0.0) + 0.50 * positive_window_rate
    drawdown_penalty = max(0.20, 1.0 - max_dd / 0.30)
    correlation_penalty = max(0.25, 1.0 - avg_corr)
    if action in {"Keep Research", "Increase Review"}:
        base += 0.40
    if action in {"Watch", "Reduce"}:
        base *= 0.50
    return float(max(base * drawdown_penalty * correlation_penalty, 0.0))


def _research_quality_for_item(item: dict, config: dict | None = None) -> dict:
    backtest = item["backtest"]
    net = backtest.get("net_metrics", {})
    row = {
        "strategy_id": backtest["strategy_id"],
        "proxy_metrics": {
            "proxy_sharpe": float(net.get("sharpe", 0.0)),
            "proxy_max_drawdown": float(net.get("max_drawdown", 0.0)),
        },
        "turnover": backtest.get("turnover", {}),
        "walk_forward": item.get("walk_forward", {}),
    }
    result = evaluate_research_quality_limits(row, config)
    status = worst_status(result["checks"])
    return {
        "eligible": status not in {"breach"},
        "status": status,
        "checks": result["checks"],
        "summary": result["summary"],
    }


def _literature_strategy_row(
    item: dict,
    risk_limit_config: dict,
    duplicate_gate: dict | None,
    current_weight: float,
    proposed_weight: float,
    capital: float,
) -> dict:
    backtest = item["backtest"]
    net = backtest.get("net_metrics", {})
    wfo = item.get("walk_forward", {})
    daily_return = _last_return(backtest)
    current_allocation_dollars = float(current_weight * capital)
    cumulative_return = float(net.get("cumulative_return", 0.0))
    row = {
        "strategy_id": backtest["strategy_id"],
        "name": backtest["name"],
        "strategy_type": _strategy_type_from_source(backtest.get("literature_source", "")),
        "status": "research_running",
        "current_weight": float(current_weight),
        "proposed_weight": float(proposed_weight),
        "allocation_change": float(proposed_weight - current_weight),
        "current_allocation_dollars": current_allocation_dollars,
        "proposed_allocation_dollars": float(proposed_weight * capital),
        "daily_return": daily_return,
        "daily_pnl": float(daily_return * current_allocation_dollars),
        "mtd_pnl": float(_period_return(backtest, "MTD") * current_allocation_dollars),
        "ytd_pnl": float(_period_return(backtest, "YTD") * current_allocation_dollars),
        "cumulative_pnl": float(cumulative_return * current_allocation_dollars),
        "sharpe": float(net.get("sharpe", 0.0)),
        "rolling_sharpe": _latest_rolling_sharpe(backtest),
        "volatility": float(net.get("annual_volatility", 0.0)),
        "max_drawdown": float(net.get("max_drawdown", 0.0)),
        "current_drawdown": float(backtest.get("risk_packet", {}).get("drawdown_behavior", {}).get("current_drawdown", 0.0)),
        "win_rate": float(net.get("win_rate", 0.0)),
        "transaction_cost_drag": float(backtest.get("turnover", {}).get("annualized_cost_drag", 0.0)),
        "signal_status": _signal_status(backtest),
        "signal_state": _signal_status(backtest),
        "regime_fit": _regime_fit(backtest),
        "factor_exposure_summary": _factor_exposure_summary(backtest),
        "data_quality_status": backtest.get("backtest_evidence", {}).get("status", "unknown"),
        "literature_source": backtest.get("literature_source"),
        "hypothesis": backtest.get("hypothesis"),
        "universe": backtest.get("universe", []),
        "rebalance": backtest.get("rebalance"),
        "signal_summary": backtest.get("signal_summary"),
        "failure_modes": backtest.get("failure_modes", []),
        "backtest_evidence": backtest.get("backtest_evidence", {}),
        "walk_forward": wfo,
        "gross_metrics": backtest.get("gross_metrics", {}),
        "net_metrics": net,
        "turnover": backtest.get("turnover", {}),
        "risk_packet": backtest.get("risk_packet", {}),
        "position_packet": backtest.get("position_packet", {}),
        "factor_exposure": backtest.get("factor_exposure", {}),
        "proxy_metrics": {
            "daily_return": daily_return,
            "proxy_sharpe": float(net.get("sharpe", 0.0)),
            "proxy_volatility": float(net.get("annual_volatility", 0.0)),
            "proxy_max_drawdown": float(net.get("max_drawdown", 0.0)),
        },
        "strategy_action_from_backtest": backtest.get("action", {}),
        "correlation_gate": duplicate_gate
        or {
            "allocation_blocker": False,
            "reason_code": "independent_enough",
            "interpretation": "No pairwise correlation breach versus current strategy set.",
        },
        "human_approval_required": True,
        "evidence_status": _literature_evidence_status(backtest, wfo),
        "bias_controls": {
            "lookahead_bias": backtest.get("backtest_evidence", {}).get("lookahead_bias_check"),
            "transaction_cost": backtest.get("backtest_evidence", {}).get("cost_assumption"),
            "survivorship_bias": backtest.get("backtest_evidence", {}).get("survivorship_bias_note"),
            "oos_walk_forward": f"{wfo.get('number_of_windows', 0)} windows; train={wfo.get('train_days')} days, test={wfo.get('test_days')} days",
        },
        "risk_manager_question_answered": {
            "what_happened": _strategy_what_happened(backtest),
            "why": _strategy_why(backtest),
            "what_to_do": backtest.get("action", {}).get("interpretation", ""),
        },
    }
    limit_status = evaluate_strategy_limits(row, risk_limit_config)
    research_quality_status = evaluate_research_quality_limits(row, risk_limit_config)
    evidence_limit_status = evaluate_evidence_limits(row, risk_limit_config)
    checks = limit_status["checks"]
    eligibility_checks = research_quality_status["checks"] + evidence_limit_status["checks"]
    row["risk_limit_checks"] = checks
    row["research_quality_checks"] = eligibility_checks
    row["risk_limit_summary"] = limit_status["summary"]
    row["research_quality_summary"] = _sum_limit_summaries([research_quality_status["summary"], evidence_limit_status["summary"]])
    row["risk_limit_categories"] = {
        "live_monitoring": limit_status,
        "research_quality": research_quality_status,
        "evidence": evidence_limit_status,
    }
    if current_weight > 0:
        row["risk_status"] = worst_status(checks)
        row["live_risk_status"] = row["risk_status"]
    else:
        row["risk_status"] = "not_applicable"
        row["live_risk_status"] = "not_applicable"
    row["research_status"] = worst_status(eligibility_checks)
    row["research_quality_status"] = _research_quality_label(row["research_status"])
    row["allocation_eligibility"] = {
        "eligible": row["research_status"] != "breach" and not row["correlation_gate"].get("allocation_blocker", False),
        "status": "eligible" if row["research_status"] != "breach" and not row["correlation_gate"].get("allocation_blocker", False) else "blocked",
        "label": "eligible"
        if row["research_status"] != "breach" and not row["correlation_gate"].get("allocation_blocker", False)
        else "blocked",
        "reason": "Passed research-quality and evidence gates." if row["research_status"] != "breach" else "Failed at least one research-quality or evidence gate.",
    }
    row["recommended_action"] = _recommended_action(
        row["live_risk_status"] if current_weight > 0 else row["research_status"],
        row["evidence_status"],
        row["correlation_gate"],
        row["allocation_eligibility"],
    )
    row["trade_decision"] = _trade_decision(row)
    return decorate_strategy_status_fields(row)


def _last_return(backtest: dict) -> float:
    values = backtest.get("return_series", {}).get("net_returns", [])
    return float(values[-1]) if values else 0.0


def _period_return(backtest: dict, period: str) -> float:
    series = backtest.get("return_series", {})
    dates = series.get("dates", [])
    returns = series.get("net_returns", [])
    if not dates or not returns:
        return 0.0
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "return": [float(value) for value in returns]})
    latest = frame["date"].max()
    if period == "MTD":
        sliced = frame[(frame["date"].dt.year == latest.year) & (frame["date"].dt.month == latest.month)]
    elif period == "YTD":
        sliced = frame[frame["date"].dt.year == latest.year]
    else:
        sliced = frame
    if sliced.empty:
        return 0.0
    return float((1.0 + sliced["return"]).prod() - 1.0)


def _latest_rolling_sharpe(backtest: dict) -> float:
    time_stability = backtest.get("risk_packet", {}).get("time_stability", {})
    for window in ["63d", "126d", "252d", "21d"]:
        if window in time_stability:
            return float(time_stability[window].get("latest_rolling_sharpe", 0.0))
    return 0.0


def _signal_status(backtest: dict) -> str:
    positions = backtest.get("position_packet", {}).get("latest_positions", [])
    gross = float(backtest.get("position_packet", {}).get("latest_gross_exposure", 0.0))
    if not positions or gross < 1e-8:
        return "inactive"
    if any(float(position.get("weight", 0.0)) < 0 for position in positions):
        return "active_long_short"
    return "active_long_only"


def _regime_fit(backtest: dict) -> dict:
    regimes = backtest.get("risk_packet", {}).get("regime_breakdown", {})
    if not regimes:
        return {"best_regime": None, "worst_regime": None, "status": "not_available"}
    scored = {
        regime: float(stats.get("sharpe", 0.0))
        for regime, stats in regimes.items()
        if int(stats.get("observations", 0)) > 20
    }
    if not scored:
        return {"best_regime": None, "worst_regime": None, "status": "insufficient_observations"}
    best = max(scored, key=scored.get)
    worst = min(scored, key=scored.get)
    return {
        "best_regime": best,
        "best_regime_sharpe": float(scored[best]),
        "worst_regime": worst,
        "worst_regime_sharpe": float(scored[worst]),
        "status": "watch" if scored[worst] < 0 else "ok",
    }


def _factor_exposure_summary(backtest: dict) -> dict:
    exposure = backtest.get("factor_exposure", {})
    concentration = exposure.get("concentration", {})
    latest = exposure.get("latest", {})
    top = concentration.get("top_factor")
    return {
        "top_factor": top,
        "top_abs_exposure": float(concentration.get("top_abs_exposure", 0.0)),
        "exposure_count": len(latest),
        "summary": f"{top}: {float(concentration.get('top_abs_exposure', 0.0)):.2f}" if top else "no material factor exposure",
    }


def _literature_evidence_status(backtest: dict, walk_forward: dict) -> str:
    evidence = backtest.get("backtest_evidence", {})
    if evidence.get("status") not in {"attached", "complete"}:
        return "missing_evidence"
    if walk_forward.get("status") != "complete":
        return "research_only"
    if int(walk_forward.get("number_of_windows", 0)) < 3:
        return "research_only"
    return "evidence_attached"


def _strategy_type_from_source(source: str) -> str:
    lowered = source.lower()
    if "worldquant" in lowered:
        return "Formulaic Alpha"
    if "replication" in lowered:
        return "Hedge Fund Replication"
    if "business" in lowered or "regime" in lowered:
        return "Macro Regime"
    if "markov" in lowered:
        return "Regime / Tail Risk"
    if "relative" in lowered or "rv" in lowered:
        return "Relative Value"
    return "Multi-Asset Strategy"


def _strategy_what_happened(backtest: dict) -> str:
    net = backtest.get("net_metrics", {})
    return (
        f"Net Sharpe {float(net.get('sharpe', 0.0)):.2f}, "
        f"annual volatility {float(net.get('annual_volatility', 0.0)):.2%}, "
        f"max drawdown {float(net.get('max_drawdown', 0.0)):.2%}, "
        f"annualized turnover {float(net.get('annualized_turnover', 0.0)):.2f}."
    )


def _strategy_why(backtest: dict) -> str:
    risk_packet = backtest.get("risk_packet", {})
    comparison = risk_packet.get("comparison_vs_benchmark", {})
    tail = risk_packet.get("tail_risk", {})
    return (
        f"SPY beta {float(comparison.get('beta', 0.0)):.2f}, "
        f"SPY correlation {float(comparison.get('correlation', 0.0)):.2f}, "
        f"99% VaR {float(tail.get('var_99', 0.0)):.2%}, "
        f"ES 95 {float(tail.get('expected_shortfall_95', 0.0)):.2%}."
    )


def _trade_decision(row: dict) -> dict:
    change = row["allocation_change"]
    if row["recommended_action"] in {"Pause", "Research Hold", "Merge / Redesign"}:
        action = "Do not add capital"
    elif change > 0.0025:
        action = "Review increase"
    elif change < -0.0025:
        action = "Review reduction"
    else:
        action = "Keep current weight"
    return {
        "action": action,
        "requires_human_approval": True,
        "rationale": row.get("risk_manager_question_answered", {}).get("what_to_do", ""),
    }


def _generate_literature_dashboard_artifact(results: list[dict], output_path: str | Path, capital: float) -> dict:
    risk_limit_config = load_risk_limits()
    strategy_ids = [item["backtest"]["strategy_id"] for item in results]
    eligibility_by_strategy = {
        item["backtest"]["strategy_id"]: _research_quality_for_item(item, risk_limit_config)
        for item in results
    }
    eligible_ids = [
        strategy_id
        for strategy_id, quality in eligibility_by_strategy.items()
        if quality["eligible"]
    ]
    eligible_weights = _equal_weights(eligible_ids)
    weights = {strategy_id: eligible_weights.get(strategy_id, 0.0) for strategy_id in strategy_ids}
    aligned = _aligned_window_from_literature(results, weights)
    investment_start = _load_investment_start()
    aligned_live = slice_aligned_window(aligned, investment_start)
    returns = aligned.as_dict()
    returns_live = aligned_live.as_dict()
    historical_research_risk_summary = portfolio_risk_summary(returns, weights, allow_residual_cash=True)
    risk_summary = historical_research_risk_summary
    portfolio_series = weighted_portfolio_series(aligned, weights)
    portfolio_series_live = weighted_portfolio_series(aligned_live, weights)
    invested_weight = float(sum(weights.values()))
    live_returns = portfolio_series_live.get("returns", [])
    live_cumulative = portfolio_series_live.get("cumulative_return", [])
    operating_period_risk = build_operating_period_risk(
        returns_live,
        weights,
        observations=aligned_live.observations,
        start_date=aligned_live.start_date,
        end_date=aligned_live.end_date,
        daily_return=float(live_returns[-1]) if live_returns else None,
        cumulative_return=float(live_cumulative[-1]) if live_cumulative else None,
    )
    portfolio_limit_status = evaluate_portfolio_limits(historical_research_risk_summary, risk_limit_config)
    operating_portfolio_limit_status = evaluate_portfolio_limits_with_availability(
        operating_period_risk["metrics"],
        risk_limit_config,
    )
    residual_cash_limit_status = evaluate_residual_cash_limit(invested_weight, risk_limit_config)
    strategy_names = {item["backtest"]["strategy_id"]: item["backtest"]["name"] for item in results}
    correlation_report = strategy_correlation_report(
        returns,
        strategy_names,
        risk_limit_config["portfolio_limits"]["max_pairwise_strategy_correlation"],
    )
    allocated_correlation_report = strategy_correlation_report(
        {strategy_id: values for strategy_id, values in returns.items() if weights.get(strategy_id, 0.0) > 0},
        {strategy_id: name for strategy_id, name in strategy_names.items() if weights.get(strategy_id, 0.0) > 0},
        risk_limit_config["portfolio_limits"]["max_pairwise_strategy_correlation"],
    )
    duplicate_exposure_map = correlation_report.get("duplicate_exposure_by_strategy", {})
    scores = {
        item["backtest"]["strategy_id"]: _score_literature_strategy(item, duplicate_exposure_map.get(item["backtest"]["strategy_id"]))
        for item in results
    }
    min_weights = {strategy_id: 0.0 for strategy_id in strategy_ids}
    max_weights = {
        strategy_id: (
            risk_limit_config["strategy_limits"].get("max_weight_default", 0.15)
            if eligibility_by_strategy[strategy_id]["eligible"]
            else 0.0
        )
        for strategy_id in strategy_ids
    }
    recommendation = propose_allocation(
        weights,
        scores,
        min_weights,
        max_weights,
        capital,
        max_turnover=risk_limit_config["portfolio_limits"].get("max_turnover_per_rebalance", 0.15),
    )
    proposed_risk_summary = portfolio_risk_summary(returns, recommendation.proposed_weights)
    proposed_portfolio_limit_status = evaluate_portfolio_limits(proposed_risk_summary, risk_limit_config)
    cost_model = TransactionCostModel()
    strategy_rows = []
    strategy_limit_checks = []
    research_quality_checks = []
    for item in results:
        strategy_id = item["backtest"]["strategy_id"]
        current = weights.get(strategy_id, 0.0)
        proposed = recommendation.proposed_weights.get(strategy_id, 0.0)
        row = _literature_strategy_row(
            item,
            risk_limit_config,
            duplicate_exposure_map.get(strategy_id),
            current,
            proposed,
            capital,
        )
        row["since_investment"] = _since_investment_metrics(
            item["backtest"],
            investment_start,
            current,
            capital,
        )
        side = "buy" if proposed > current else "sell"
        row["rebalance_trade"] = {
            "side": side.upper() if abs(proposed - current) > 1e-10 else "HOLD",
            "notional": float(abs(proposed - current) * capital),
            "estimated_cost": float(cost_model.cost_for_trade(abs(proposed - current) * capital, side)) if abs(proposed - current) > 1e-10 else 0.0,
            "cost_bps": 5.0 if abs(proposed - current) > 1e-10 else 0.0,
        }
        strategy_limit_checks.extend(row["risk_limit_checks"] if current > 0 else [])
        research_quality_checks.extend(row["research_quality_checks"])
        strategy_rows.append(row)

    factor_analytics = _portfolio_factor_analytics(strategy_rows, recommendation.current_weights, recommendation.proposed_weights)
    factor_analytics["cash_semantics"] = _cash_semantics(
        factor_analytics.get("portfolio_factor_exposure_current", {}),
        invested_weight,
    )
    factor_analytics["factor_display_labels"] = {
        "cash": "Treasury-bill / liquidity proxy exposure",
    }
    weight_changes = {
        strategy_id: float(recommendation.proposed_weights.get(strategy_id, 0.0) - recommendation.current_weights.get(strategy_id, 0.0))
        for strategy_id in strategy_ids
    }
    rebalance_trade_list = [
        {
            "strategy_id": row["strategy_id"],
            "strategy": row["name"],
            "side": row["rebalance_trade"]["side"],
            "current_weight": row["current_weight"],
            "proposed_weight": row["proposed_weight"],
            "weight_change": row["allocation_change"],
            "notional": row["rebalance_trade"]["notional"],
            "estimated_cost": row["rebalance_trade"]["estimated_cost"],
            "recommended_action": row["recommended_action"],
            "requires_human_approval": True,
        }
        for row in strategy_rows
        if row["rebalance_trade"]["side"] != "HOLD"
    ]
    turnover = float(sum(abs(value) for value in weight_changes.values()))
    allocation_limit_input = {
        "weight_changes": weight_changes,
        "turnover": turnover,
        "estimated_transaction_cost": recommendation.estimated_transaction_cost,
        "capital": capital,
    }
    factor_limit_status = evaluate_factor_limits(factor_analytics, risk_limit_config)
    scenario_limit_status = evaluate_scenario_limits(factor_analytics, risk_limit_config)
    correlation_limit_status = evaluate_correlation_limits(allocated_correlation_report, risk_limit_config)
    rebalance_limit_status = evaluate_rebalance_limits(allocation_limit_input, risk_limit_config)
    allocated_strategy_summaries = [
        row["risk_limit_summary"] for row in strategy_rows if float(row.get("current_weight", 0.0)) > 0
    ]
    risk_limit_summary = {
        "policy_metadata": risk_limit_config.get("policy_metadata", {}),
        "portfolio": portfolio_limit_status,
        "portfolio_operating": operating_portfolio_limit_status,
        "portfolio_proposed": proposed_portfolio_limit_status,
        "residual_cash": residual_cash_limit_status,
        "factors": factor_limit_status,
        "scenarios": scenario_limit_status,
        "correlation": correlation_limit_status,
        "rebalance": rebalance_limit_status,
        "strategies": {
            "summary": _sum_limit_summaries(allocated_strategy_summaries),
            "checks": strategy_limit_checks,
        },
        "research_quality": {
            "summary": summarize_limit_status(research_quality_checks),
            "checks": research_quality_checks,
        },
        "checks": [],
        "aggregation_note": "Use risk_status_summary for canonical scoped counts. Flat checks are deprecated to avoid double counting.",
    }
    data_quality = _literature_data_quality(results, aligned)
    market_snapshot = load_market_snapshot()
    market_as_of = None
    for item in results:
        end_date = item["backtest"].get("backtest_evidence", {}).get("end_date")
        if end_date:
            market_as_of = end_date
            break
    if market_snapshot.get("as_of"):
        market_as_of = market_snapshot.get("as_of")
    build_metadata = _artifact_build_metadata(
        market_as_of=market_as_of,
        operating_period_start=investment_start,
        operating_period_end=aligned_live.end_date,
    )
    data_classification = _data_classification(
        market_as_of=market_as_of,
        retrieved_at=build_metadata["data_retrieved_at"],
    )
    data_quality_checks = [
        enrich_check(
            {
                "limit_id": "DATA_COMMON_WINDOW",
                "metric": "common_portfolio_risk_window_observations",
                "current_value": data_quality.get("common_portfolio_risk_window_observations", 0),
                "breach_threshold": 252,
                "status": "ok" if data_quality.get("common_portfolio_risk_window_observations", 0) >= 252 else "warning",
                "action": "Review data alignment",
                "explanation": "Common overlapping research window observation count.",
            },
            scope="data_quality",
            subject_id="portfolio",
            allocation_relevance="research",
            applicability="research",
        )
    ]
    portfolio_live_checks = [
        enrich_check(
            check,
            scope="portfolio_live",
            subject_id="portfolio",
            allocation_relevance="allocated_model",
            applicability="operating_period",
        )
        for check in operating_portfolio_limit_status["checks"]
    ]
    allocated_strategy_live_checks = [
        enrich_check(
            check,
            scope="allocated_strategy_live",
            subject_id=str(check.get("scope", "strategy")),
            allocation_relevance="allocated_model",
            applicability="allocated_model",
        )
        for check in strategy_limit_checks
    ]
    enriched_research_checks = [
        enrich_check(
            check,
            scope="research_quality",
            subject_id=str(check.get("scope", "strategy")),
            allocation_relevance="eligibility",
            applicability="research",
        )
        for check in research_quality_checks
    ]
    enriched_factor_checks = [
        enrich_check(
            check,
            scope="factor",
            subject_id="portfolio",
            allocation_relevance="allocated_model",
            applicability="allocated_model",
        )
        for check in factor_limit_status["checks"]
    ]
    enriched_scenario_checks = [
        enrich_check(
            check,
            scope="scenario",
            subject_id="portfolio",
            allocation_relevance="allocated_model",
            applicability="allocated_model",
        )
        for check in scenario_limit_status["checks"]
    ]
    enriched_correlation_checks = [
        enrich_check(
            check,
            scope="correlation",
            subject_id="portfolio",
            allocation_relevance="allocated_model",
            applicability="allocated_model",
        )
        for check in correlation_limit_status["checks"]
    ]
    enriched_rebalance_checks = [
        enrich_check(
            check,
            scope="rebalance",
            subject_id="portfolio",
            allocation_relevance="proposed_allocation",
            applicability="proposed_allocation",
        )
        for check in rebalance_limit_status["checks"]
    ]
    risk_status_summary = build_risk_status_summary(
        portfolio_checks=portfolio_live_checks
        + [
            enrich_check(
                check,
                scope="portfolio_live",
                subject_id="portfolio",
                allocation_relevance="allocated_model",
                applicability="operating_period",
            )
            for check in residual_cash_limit_status["checks"]
        ],
        allocated_strategy_checks=allocated_strategy_live_checks,
        research_quality_checks=enriched_research_checks,
        factor_checks=enriched_factor_checks,
        scenario_checks=enriched_scenario_checks,
        correlation_checks=enriched_correlation_checks,
        rebalance_checks=enriched_rebalance_checks,
        residual_cash_checks=[],
        data_quality_checks=data_quality_checks,
        governance_checks=[],
    )
    decision_allocation = {
        "current_weights": recommendation.current_weights,
        "proposed_weights": recommendation.proposed_weights,
        "weight_changes": weight_changes,
        "turnover": turnover,
        "estimated_transaction_cost": recommendation.estimated_transaction_cost,
        "capital": capital,
    }
    decision_review = review_decisions(
        strategy_rows,
        decision_allocation,
        risk_limit_summary,
        factor_analytics,
        risk_summary,
        proposed_risk_summary,
    )
    decision_workflow = build_decision_workflow(
        date.today().isoformat(),
        {
            **decision_allocation,
            "rebalance_trade_list": rebalance_trade_list,
        },
        decision_review,
        risk_limit_summary,
    )
    strategy_review_map = {
        row["strategy_id"]: row for row in decision_review.get("strategy_decision_reviews", [])
    }
    for row in strategy_rows:
        row["decision_review"] = strategy_review_map.get(row["strategy_id"], {})
        row["final_action_after_double_check"] = row["decision_review"].get(
            "final_action_after_double_check",
            row["recommended_action"],
        )
    market_summary = summarize_market_risk(market_snapshot)
    news_snapshot = load_news_snapshot()
    news_risk = analyze_news_risk(news_snapshot)
    literature_modules = _load_literature_modules()
    replication_clone = _load_replication_snapshot()
    risk_recommendations = build_recommendations(
        market_summary,
        news_risk,
        {
            "estimated_transaction_cost": recommendation.estimated_transaction_cost,
            "approval_required": recommendation.approval_required,
            "rationale": recommendation.rationale,
        },
        factor_checks=[check for check in factor_limit_status["checks"] if check.get("status") != "ok"],
        portfolio_limit_checks=[
            check
            for check in operating_portfolio_limit_status["checks"] + factor_limit_status["checks"]
            if check.get("status") not in {"ok", "not_evaluated"}
        ],
        factor_exposure=factor_analytics.get("portfolio_factor_exposure_current", {}),
    )
    artifact = {
        "platform": "Risk Manager Platform",
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "build_metadata": build_metadata,
        "data_classification": data_classification,
        "as_of_date": date.today().isoformat(),
        "initial_capital": capital,
        "strategy_count": len(strategy_rows),
        "strategy_return_source": "literature_backtest_net_returns_yfinance_proxy",
        "market_data_mode": "research_market_proxy",
        "ui_contract": _load_workstation_ui_contract(),
        "data_quality": data_quality,
        "historical_research_risk_summary": historical_research_risk_summary,
        "risk_summary": historical_research_risk_summary,
        "operating_period_risk": operating_period_risk,
        "risk_summary_proposed": proposed_risk_summary,
        "risk_status_summary": risk_status_summary,
        "risk_limits": risk_limit_summary,
        "decision_review": decision_review,
        "decision_workflow": decision_workflow,
        "investment_context": {
            "start_date": investment_start,
            "initial_capital": capital,
            "invested_weight": invested_weight,
            "residual_cash_weight": float(max(0.0, 1.0 - invested_weight)),
            "label": "Operating-period model portfolio view",
            "note": (
                "Operating-period metrics use historical ETF proxy returns sliced from the "
                "configured investment start date. They are not live position or fill data."
            ),
        },
        "portfolio_series": portfolio_series,
        "portfolio_series_live": portfolio_series_live,
        "factors": factor_analytics,
        "correlation": correlation_report,
        "allocation": {
            "current_weights": recommendation.current_weights,
            "proposed_weights": recommendation.proposed_weights,
            "weight_changes": weight_changes,
            "rebalance_trade_list": rebalance_trade_list,
            "turnover": turnover,
            "estimated_transaction_cost": recommendation.estimated_transaction_cost,
            "approval_required": recommendation.approval_required,
            "rationale": recommendation.rationale,
            "recommendation": "Human review required before any real allocation change.",
            "final_decision_after_double_check": decision_review["final_decision"],
            "approval_status_after_double_check": decision_review["approval_status"],
            "expected_impact": decision_review["expected_impact"],
            "double_check_gates": decision_review["double_check_gates"],
            "human_approval_required": True,
            "risk_before": risk_summary,
            "risk_after": proposed_risk_summary,
            "factor_concentration_before_after": {
                "current": factor_analytics["portfolio_factor_concentration_current"],
                "proposed": factor_analytics["portfolio_factor_concentration_proposed"],
            },
            "correlation_before_after": {
                "current": correlation_report.get("summary", {}),
                "proposed": correlation_report.get("summary", {}),
                "note": "Current prototype keeps strategy return correlations fixed and changes allocation weights only.",
            },
            "policy": {
                "not_blind_sharpe_max": True,
                "uses_evidence_score": True,
                "uses_drawdown_penalty": True,
                "uses_correlation_blocker": True,
                "uses_turnover_cap": True,
                "requires_human_approval": True,
            },
            "before_after": {
                "current": risk_summary,
                "proposed": proposed_risk_summary,
                "limit_status_current": portfolio_limit_status,
                "limit_status_proposed": proposed_portfolio_limit_status,
            },
            "optimizer_constraints": {
                "max_single_strategy_weight": risk_limit_config["strategy_limits"].get("max_weight_default", 0.15),
                "max_turnover_per_rebalance": risk_limit_config["portfolio_limits"].get("max_turnover_per_rebalance", 0.15),
                "transaction_cost_budget_bps": risk_limit_config["portfolio_limits"].get("max_transaction_cost_budget_bps_per_rebalance", 8),
                "max_pairwise_strategy_correlation": risk_limit_config["portfolio_limits"].get("max_pairwise_strategy_correlation", 0.75),
                "human_approval_required": True,
            },
        },
        "market_monitor": market_summary,
        "news_risk": news_risk,
        "recommendations": risk_recommendations,
        "literature_modules": literature_modules,
        "replication_clone": replication_clone,
        "literature_strategy_backtests": _load_literature_strategy_backtests(),
        "strategies": strategy_rows,
        "daily_decision_log": _daily_decision_log(strategy_rows, recommendation),
        "rebalance_simulation": build_simulation_context(
            returns,
            strategy_rows,
            recommendation.current_weights,
            recommendation.proposed_weights,
            capital,
            risk_limit_config,
        ),
        "dashboard_tabs": [
            "Portfolio Command Center",
            "Strategy Monitor",
            "Allocation & Rebalance",
            "Risk Factors & Exposure",
            "Correlation & Diversification",
            "Market & Macro Monitor",
            "Backtesting & Research Lab",
            "Strategy Library & Workflow",
            "Daily Risk Report / Decision Log",
        ],
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, separators=(",", ":")), encoding="utf-8")
    return artifact


def _daily_decision_log(strategy_rows: list[dict], recommendation) -> list[dict]:
    actions = []
    for row in strategy_rows:
        if row["recommended_action"] != "Keep" or abs(row["allocation_change"]) > 0.0025:
            actions.append(
                {
                    "strategy_id": row["strategy_id"],
                    "strategy": row["name"],
                    "recommended_action": row["recommended_action"],
                    "trade_decision": row["trade_decision"]["action"],
                    "risk_status": row["risk_status"],
                    "evidence_status": row["evidence_status"],
                    "requires_human_approval": True,
                    "note": row["trade_decision"]["rationale"],
                }
            )
    actions.append(
        {
            "scope": "portfolio",
            "recommended_action": "Human review required",
            "estimated_transaction_cost": recommendation.estimated_transaction_cost,
            "requires_human_approval": True,
            "note": "System can recommend allocation changes, but real capital changes require human approval.",
        }
    )
    return actions


def _portfolio_factor_analytics(strategy_rows: list[dict], current_weights: dict[str, float], proposed_weights: dict[str, float]) -> dict:
    matrix = []
    for row in strategy_rows:
        latest = row.get("factor_exposure", {}).get("latest", {})
        compact = {
            "strategy_id": row["strategy_id"],
            "strategy": row["name"],
            "current_weight": current_weights.get(row["strategy_id"], 0.0),
            "proposed_weight": proposed_weights.get(row["strategy_id"], 0.0),
        }
        compact.update({factor: float(value) for factor, value in latest.items()})
        matrix.append(compact)

    current_exposure = _weighted_factor_exposure(strategy_rows, current_weights)
    proposed_exposure = _weighted_factor_exposure(strategy_rows, proposed_weights)
    contribution_to_risk = _factor_contribution_to_risk(current_exposure)
    contribution_to_return = _factor_contribution_to_return(strategy_rows, current_weights)
    scenario_shocks = _scenario_shock_table(current_exposure)
    factor_changes = {
        factor: float(proposed_exposure.get(factor, 0.0) - current_exposure.get(factor, 0.0))
        for factor in sorted(set(current_exposure) | set(proposed_exposure))
    }
    return {
        "method": "ETF proxy exposure aggregation. This is a prototype factor-risk layer, not a licensed Barra model.",
        "strategy_by_factor_matrix": matrix,
        "portfolio_factor_exposure_current": current_exposure,
        "portfolio_factor_exposure_proposed": proposed_exposure,
        "portfolio_factor_change": factor_changes,
        "portfolio_factor_concentration_current": _factor_concentration(current_exposure),
        "portfolio_factor_concentration_proposed": _factor_concentration(proposed_exposure),
        "factor_contribution_to_risk": contribution_to_risk,
        "factor_contribution_to_return": contribution_to_return,
        "scenario_shock_table": scenario_shocks,
        "human_review_alerts": _factor_human_review_alerts(current_exposure, proposed_exposure, scenario_shocks),
    }


def _weighted_factor_exposure(strategy_rows: list[dict], weights: dict[str, float]) -> dict[str, float]:
    exposure: dict[str, float] = {}
    for row in strategy_rows:
        weight = float(weights.get(row["strategy_id"], 0.0))
        latest = row.get("factor_exposure", {}).get("latest", {})
        for factor, value in latest.items():
            exposure[factor] = exposure.get(factor, 0.0) + weight * float(value)
    return {factor: float(value) for factor, value in sorted(exposure.items()) if abs(value) > 1e-10}


def _factor_concentration(exposure: dict[str, float]) -> dict:
    abs_exposure = {factor: abs(value) for factor, value in exposure.items()}
    total = sum(abs_exposure.values())
    if not total:
        return {"top_factor": None, "top_abs_exposure": 0.0, "herfindahl_abs_exposure": 0.0}
    top_factor = max(abs_exposure, key=abs_exposure.get)
    return {
        "top_factor": top_factor,
        "top_abs_exposure": float(abs_exposure[top_factor]),
        "gross_factor_exposure": float(total),
        "herfindahl_abs_exposure": float(sum((value / total) ** 2 for value in abs_exposure.values())),
    }


def _factor_contribution_to_risk(exposure: dict[str, float]) -> list[dict]:
    total = sum(abs(value) for value in exposure.values())
    if not total:
        return []
    rows = [
        {
            "factor": factor,
            "exposure": float(value),
            "abs_exposure": float(abs(value)),
            "risk_share": float(abs(value) / total),
            "status": _factor_status(factor, abs(value)),
        }
        for factor, value in exposure.items()
    ]
    return sorted(rows, key=lambda row: row["risk_share"], reverse=True)


def _factor_contribution_to_return(strategy_rows: list[dict], weights: dict[str, float]) -> list[dict]:
    contribution: dict[str, float] = {}
    for row in strategy_rows:
        latest_return = float(row.get("proxy_metrics", {}).get("daily_return", 0.0))
        weighted_return = float(weights.get(row["strategy_id"], 0.0)) * latest_return
        exposures = row.get("factor_exposure", {}).get("latest", {})
        abs_total = sum(abs(float(value)) for value in exposures.values())
        if not abs_total:
            continue
        for factor, value in exposures.items():
            contribution[factor] = contribution.get(factor, 0.0) + weighted_return * abs(float(value)) / abs_total
    return [
        {"factor": factor, "estimated_daily_return_contribution": float(value)}
        for factor, value in sorted(contribution.items(), key=lambda item: abs(item[1]), reverse=True)
    ]


def _scenario_shock_table(exposure: dict[str, float]) -> list[dict]:
    scenarios = [
        {
            "scenario": "Equity -5%",
            "shock": {"equity_beta": -0.05, "growth_style": -0.04, "small_cap": -0.06, "international_equity": -0.04, "emerging_market": -0.06},
            "review_threshold": -0.01,
        },
        {
            "scenario": "Rates +50 bps",
            "shock": {"rates_duration": -0.035, "inflation_linked": -0.015},
            "review_threshold": -0.006,
        },
        {
            "scenario": "Credit spread widening",
            "shock": {"credit_spread": -0.04, "convertible": -0.025, "event_driven": -0.015},
            "review_threshold": -0.008,
        },
        {
            "scenario": "USD +3%",
            "shock": {"usd_fx": 0.03, "emerging_market": -0.025, "commodity_beta": -0.015},
            "review_threshold": -0.006,
        },
        {
            "scenario": "Volatility spike",
            "shock": {"volatility": 0.12, "short_vol": -0.12, "tail_hedge": 0.08, "equity_beta": -0.035},
            "review_threshold": -0.01,
        },
        {
            "scenario": "Oil / commodity +10%",
            "shock": {"commodity_beta": 0.10, "oil_beta": 0.10, "inflation_beta": 0.04, "rates_duration": -0.015},
            "review_threshold": -0.006,
        },
    ]
    output = []
    for scenario in scenarios:
        impact = sum(float(exposure.get(factor, 0.0)) * shock for factor, shock in scenario["shock"].items())
        output.append(
            {
                "scenario": scenario["scenario"],
                "estimated_portfolio_impact": float(impact),
                "risk_status": "breach" if impact <= scenario["review_threshold"] else "watch" if impact < 0 else "ok",
                "drivers": [
                    {"factor": factor, "shock": float(shock), "exposure": float(exposure.get(factor, 0.0))}
                    for factor, shock in scenario["shock"].items()
                    if abs(exposure.get(factor, 0.0)) > 1e-10
                ],
            }
        )
    return output


def _factor_human_review_alerts(current: dict[str, float], proposed: dict[str, float], scenarios: list[dict]) -> list[dict]:
    alerts = []
    concentration = _factor_concentration(current)
    if concentration.get("herfindahl_abs_exposure", 0.0) >= 0.35:
        alerts.append(
            {
                "severity": "warning",
                "topic": "factor_concentration",
                "message": f"Top factor concentration is elevated: {concentration.get('top_factor')}.",
            }
        )
    for factor, change in _factor_delta(current, proposed).items():
        if abs(change) >= 0.03:
            alerts.append(
                {
                    "severity": "watch",
                    "topic": "factor_change",
                    "message": f"Proposed rebalance changes {factor} exposure by {change:.2%}.",
                }
            )
    for scenario in scenarios:
        if scenario["risk_status"] in {"watch", "breach"}:
            alerts.append(
                {
                    "severity": scenario["risk_status"],
                    "topic": "scenario_shock",
                    "message": f"{scenario['scenario']} estimated impact {scenario['estimated_portfolio_impact']:.2%}.",
                }
            )
    return alerts


def _factor_delta(current: dict[str, float], proposed: dict[str, float]) -> dict[str, float]:
    return {
        factor: float(proposed.get(factor, 0.0) - current.get(factor, 0.0))
        for factor in sorted(set(current) | set(proposed))
    }


def _factor_status(factor: str, abs_exposure: float) -> str:
    if factor == "cash":
        if abs_exposure >= 0.60:
            return "watch"
        return "ok"
    if abs_exposure >= 0.12:
        return "breach"
    if abs_exposure >= 0.08:
        return "warning"
    if abs_exposure >= 0.05:
        return "watch"
    return "ok"


def _literature_data_quality(results: list[dict], aligned) -> dict:
    observations = []
    starts = []
    ends = []
    missing = []
    for item in results:
        backtest = item["backtest"]
        evidence = backtest.get("backtest_evidence", {})
        obs = int(evidence.get("observations", 0) or 0)
        observations.append(obs)
        if evidence.get("start_date"):
            starts.append(evidence["start_date"])
        if evidence.get("end_date"):
            ends.append(evidence["end_date"])
        if not backtest.get("return_series", {}).get("net_returns"):
            missing.append(backtest["strategy_id"])
    return {
        "source": "yfinance ETF proxy panel",
        "strategy_count": len(results),
        "missing_return_series": missing,
        "min_strategy_observations": min(observations) if observations else 0,
        "max_strategy_observations": max(observations) if observations else 0,
        "common_portfolio_risk_window_observations": aligned.observations,
        "common_portfolio_risk_window_start": aligned.start_date,
        "common_portfolio_risk_window_end": aligned.end_date,
        "earliest_strategy_start": min(starts) if starts else None,
        "latest_strategy_end": max(ends) if ends else None,
        "transaction_cost_included": True,
        "cost_assumption": "5 bps buy, 5 bps sell, turnover-based",
        "alignment_method": aligned.alignment_method,
        "static_current_weight_reconstruction": {
            "label": "Static current-weight historical reconstruction",
            "description": (
                "Long-history portfolio charts apply today's model weights to past strategy returns. "
                "This is a research diagnostic only and is not an investable live track record."
            ),
            "look_ahead_limitation": "Selection uses current allocation; not release-timed investability.",
        },
        "missing_data_policy": "availability_aware_inner_join_no_fillna_zero",
        "important_note": (
            "Portfolio-level risk, correlation, chart series, and rebalance simulation use the same "
            "common inner-join calendar window across strategy net returns. Individual strategy pages "
            "keep their full available backtest history."
        ),
    }


def generate_dashboard_artifact(
    registry_path: str | Path,
    output_path: str | Path,
    capital: float = 1_000_000.0,
) -> dict:
    literature_strategy_backtests = _load_literature_strategy_backtests()
    literature_results = _literature_result_rows(literature_strategy_backtests)
    if literature_results:
        return _generate_literature_dashboard_artifact(literature_results, output_path, capital)

    strategies = load_strategy_registry(registry_path)
    weights = {record.strategy_id: record.target_weight for record in strategies}
    validate_weights(weights, tolerance=1e-6)
    returns = _strategy_proxy_returns_from_prices(strategies)
    strategy_metrics = _strategy_proxy_metrics(returns)
    portfolio_series = _portfolio_chart_series(returns, weights)
    available_price_tickers = _available_price_tickers()
    risk_summary = portfolio_risk_summary(returns, weights)
    risk_limit_config = load_risk_limits()
    portfolio_limit_status = evaluate_portfolio_limits(risk_summary, risk_limit_config)
    strategy_names = {record.strategy_id: record.name for record in strategies}
    correlation_report = strategy_correlation_report(
        returns,
        strategy_names,
        risk_limit_config["portfolio_limits"]["max_pairwise_strategy_correlation"],
    )
    scores = {record.strategy_id: max(0.1, 1.0 - idx * 0.02) for idx, record in enumerate(strategies)}
    min_weights = {record.strategy_id: record.min_weight for record in strategies}
    max_weights = {record.strategy_id: record.max_weight for record in strategies}
    recommendation = propose_allocation(weights, scores, min_weights, max_weights, capital)
    market_snapshot = load_market_snapshot()
    market_summary = summarize_market_risk(market_snapshot)
    news_snapshot = load_news_snapshot()
    news_risk = analyze_news_risk(news_snapshot)
    literature_modules = _load_literature_modules()
    replication_clone = _load_replication_snapshot()
    literature_strategy_backtests = _load_literature_strategy_backtests()
    risk_recommendations = build_recommendations(
        market_summary,
        news_risk,
        {
            "estimated_transaction_cost": recommendation.estimated_transaction_cost,
            "approval_required": recommendation.approval_required,
            "rationale": recommendation.rationale,
        },
        portfolio_limit_checks=[check for check in portfolio_limit_status.get("checks", []) if check.get("status") != "ok"],
    )

    strategy_rows = []
    strategy_limit_checks = []
    duplicate_exposure_map = correlation_report.get("duplicate_exposure_by_strategy", {})
    for record in strategies:
        row = {
            "strategy_id": record.strategy_id,
            "name": record.name,
            "strategy_type": record.strategy_type,
            "status": record.status,
            "target_weight": record.target_weight,
            "risk_status": record.raw.get("risk_status", "watch"),
            "backtest_status": record.raw["backtest_status"],
            "walk_forward_status": record.raw["walk_forward_status"],
            "failure_modes": record.raw["failure_modes"],
            "proxy_metrics": strategy_metrics.get(record.strategy_id, {}),
            "proxy_universe": [
                ticker
                for ticker in (record.raw.get("proxy_universe") or record.raw.get("universe", []))
                if str(ticker).replace("^VIX", "VIX") in available_price_tickers
            ],
        }
        limit_status = evaluate_strategy_limits(row, risk_limit_config)
        checks = limit_status["checks"]
        strategy_limit_checks.extend(checks)
        row["risk_limit_checks"] = checks
        row["risk_limit_summary"] = limit_status["summary"]
        row["risk_status"] = worst_status(checks)
        row["evidence_status"] = _evidence_status(row["backtest_status"], row["walk_forward_status"])
        row["correlation_gate"] = duplicate_exposure_map.get(
            record.strategy_id,
            {
                "allocation_blocker": False,
                "reason_code": "independent_enough",
                "interpretation": "No pairwise correlation breach versus current strategy set.",
            },
        )
        row["recommended_action"] = _recommended_action(row["risk_status"], row["evidence_status"], row["correlation_gate"])
        row["human_approval_required"] = row["recommended_action"] != "Keep"
        strategy_rows.append(row)

    all_limit_checks = portfolio_limit_status["checks"] + strategy_limit_checks
    risk_limit_summary = {
        "portfolio": portfolio_limit_status,
        "strategies": {
            "summary": _sum_limit_summaries([row["risk_limit_summary"] for row in strategy_rows]),
            "checks": strategy_limit_checks,
        },
        "all": _sum_limit_summaries([portfolio_limit_status["summary"]] + [row["risk_limit_summary"] for row in strategy_rows]),
        "checks": all_limit_checks,
    }

    artifact = {
        "platform": "Risk Manager Platform",
        "as_of_date": date.today().isoformat(),
        "initial_capital": capital,
        "strategy_count": len(strategies),
        "risk_summary": risk_summary,
        "risk_limits": risk_limit_summary,
        "portfolio_series": portfolio_series,
        "correlation": correlation_report,
        "allocation": {
            "current_weights": recommendation.current_weights,
            "proposed_weights": recommendation.proposed_weights,
            "estimated_transaction_cost": recommendation.estimated_transaction_cost,
            "approval_required": recommendation.approval_required,
            "rationale": recommendation.rationale,
        },
        "strategy_return_source": "yfinance_equal_weight_proxy" if Path("data/processed/market_price_history.csv").exists() else "sample_synthetic",
        "ui_contract": _load_workstation_ui_contract(),
        "market_monitor": market_summary,
        "news_risk": news_risk,
        "recommendations": risk_recommendations,
        "literature_modules": literature_modules,
        "replication_clone": replication_clone,
        "literature_strategy_backtests": literature_strategy_backtests,
        "strategies": strategy_rows,
        "dashboard_tabs": [
            "Portfolio Command Center",
            "Strategy Monitor",
            "Allocation & Rebalance",
            "Risk Factors & Exposure",
            "Correlation & Diversification",
            "Market & Macro Monitor",
            "Backtesting & Research Lab",
            "Strategy Library & Workflow",
            "Daily Risk Report / Decision Log",
        ],
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, separators=(",", ":")), encoding="utf-8")
    return artifact


def _sum_limit_summaries(summaries: list[dict[str, int]]) -> dict[str, int]:
    total = {"ok": 0, "watch": 0, "warning": 0, "breach": 0}
    for summary in summaries:
        for key in total:
            total[key] += int(summary.get(key, 0))
    return total


def _evidence_status(backtest_status: str, walk_forward_status: str) -> str:
    combined = f"{backtest_status} {walk_forward_status}".lower()
    if "pending" in combined:
        return "missing_evidence"
    if "research" in combined:
        return "research_only"
    return "evidence_attached"


def _recommended_action(
    risk_status: str,
    evidence_status: str,
    correlation_gate: dict | None = None,
    allocation_eligibility: dict | None = None,
) -> str:
    if evidence_status == "missing_evidence":
        return "Research Hold"
    if correlation_gate and correlation_gate.get("allocation_blocker"):
        return "Merge / Redesign"
    if allocation_eligibility and not allocation_eligibility.get("eligible", False):
        return "Research Hold / Retire Review"
    if risk_status == "breach":
        return "Pause"
    if risk_status == "warning":
        return "Reduce or Hedge"
    if risk_status == "watch":
        return "Watch"
    return "Keep"


def main() -> None:
    generate_dashboard_artifact(
        Path("data/config/strategy_registry.json"),
        Path("output/dashboard_artifact.json"),
    )


if __name__ == "__main__":
    main()
