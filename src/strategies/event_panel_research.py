"""Exact filing-event panel and final event/hedged strategy batch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.risk.performance import max_drawdown, sharpe_ratio
from src.strategies.diverse_strategy_research import _active_returns, _market_proxy_regime_labels
from src.strategies.expanded_selection_research import MIN_CROSS_SECTION, OHLCV_CACHE, _mask, load_expanded_facts
from src.strategies.final_challenge_research import _contribution_diagnostics, _orthogonalize, _portfolio_value
from src.strategies.fundamental_data import build_filing_event_panel
from src.strategies.fundamental_research import BUY_BPS, SELL_BPS, _summary, build_trade_log, run_candidate
from src.strategies.strategy_factory import StrategyContext, StrategySpec, build_execution_returns, common_eligibility, load_context, rank_and_weight
from src.strategies.universe_foundation import diagnostic_broad_membership
from src.strategies.worldquant.data_loader import load_ohlcv_csv, ohlcv_long_to_panels
from src.strategies.worldquant.portfolio_returns import build_asset_return_panel, compute_portfolio_returns_from_weights

PACK_ID = "EVENT_PANEL_FINAL_FOUR_STRATEGY_BATCH_V1"
OUTPUT_ROOT = Path("output/research/event_panel_final_four_strategy_batch_v1")
PROXY_PATH = Path("data/raw/fundamental_research/growth_inflation_proxy_ohlcv.csv")
EVENT_HOLD_DAYS = 20
CANDIDATE_IDS = (
    "CASH_FLOW_INFLECTION_CONTINUATION", "HIGH_CONVICTION_FILING_DRIFT_V2", "HEDGED_RESIDUAL_MOMENTUM_V3",
    "POST_FILING_MARGIN_ACCELERATION", "POST_FILING_CASH_FLOW_SURPRISE", "DEBT_REDUCTION_EVENT_DRIFT",
    "FCF_INFLECTION_QUALITY", "PROFITABILITY_TURNAROUND_MATCHED_CONTROL",
)
RATIONALES = {
    "CASH_FLOW_INFLECTION_CONTINUATION": "Post-publication continuation after positive operating-cash-flow inflection.",
    "HIGH_CONVICTION_FILING_DRIFT_V2": "Post-publication drift after broad revenue, earnings, and cash-flow improvement.",
    "HEDGED_RESIDUAL_MOMENTUM_V3": "Orthogonal residual momentum with explicit SPY beta hedge and hedge costs.",
    "POST_FILING_MARGIN_ACCELERATION": "Post-publication continuation after operating-income growth exceeds revenue growth.",
    "POST_FILING_CASH_FLOW_SURPRISE": "Post-publication continuation after unusually strong operating-cash-flow change.",
    "DEBT_REDUCTION_EVENT_DRIFT": "Post-publication drift after liabilities decline with cash-flow confirmation.",
    "FCF_INFLECTION_QUALITY": "Post-publication free-cash-flow inflection with earnings-quality confirmation.",
    "PROFITABILITY_TURNAROUND_MATCHED_CONTROL": "Causal-inspired diagnostic after profitability turnaround and prior price stress.",
}


def _event_wide(events: pd.DataFrame) -> pd.DataFrame:
    keys = ["first_valid_trading_date", "ticker", "accession_number"]
    changes = events.pivot_table(index=keys, columns="field", values="point_in_time_change", aggfunc="last")
    values = events.pivot_table(index=keys, columns="field", values="value", aggfunc="last").add_prefix("value_")
    return changes.join(values, how="outer")


def _rank(frame: pd.DataFrame, columns: list[str], minimum: int = 2) -> pd.Series:
    parts = [frame.reindex(columns=[column])[column].groupby(level="first_valid_trading_date").rank(pct=True) for column in columns]
    ranked = pd.concat(parts, axis=1)
    return ranked.mean(axis=1, skipna=True).where(ranked.notna().sum(axis=1) >= minimum)


def event_scores(events: pd.DataFrame, context: StrategyContext) -> dict[str, pd.DataFrame]:
    wide = _event_wide(events)
    wide = wide.replace([np.inf, -np.inf], np.nan)
    ocf = wide.get("operating_cash_flow", pd.Series(index=wide.index, dtype=float))
    revenue = wide.get("revenue", pd.Series(index=wide.index, dtype=float))
    op = wide.get("operating_income", pd.Series(index=wide.index, dtype=float))
    net = wide.get("net_income", pd.Series(index=wide.index, dtype=float))
    liabilities = wide.get("liabilities", pd.Series(index=wide.index, dtype=float))
    capex = wide.get("capex", pd.Series(index=wide.index, dtype=float))
    assets = wide.get("assets", pd.Series(index=wide.index, dtype=float))
    cash_positive = wide.get("value_operating_cash_flow", pd.Series(index=wide.index, dtype=float)).gt(0)
    raw = {
        "CASH_FLOW_INFLECTION_CONTINUATION": ocf.groupby(level=0).rank(pct=True).where(ocf.gt(0) & cash_positive),
        "HIGH_CONVICTION_FILING_DRIFT_V2": _rank(wide, ["revenue", "operating_income", "operating_cash_flow", "net_income"], 3).where(ocf.gt(0)),
        "POST_FILING_MARGIN_ACCELERATION": (op - revenue).groupby(level=0).rank(pct=True).where((op - revenue).gt(0)),
        "POST_FILING_CASH_FLOW_SURPRISE": ocf.groupby(level=0).rank(pct=True).where(ocf.gt(0)),
        "DEBT_REDUCTION_EVENT_DRIFT": _rank(wide.assign(negative_liabilities=-liabilities), ["negative_liabilities", "operating_cash_flow"], 2).where(liabilities.lt(0)),
        "FCF_INFLECTION_QUALITY": _rank(wide.assign(fcf_change=ocf-capex), ["fcf_change", "operating_cash_flow", "net_income"], 2).where((ocf-capex).gt(0)),
        "PROFITABILITY_TURNAROUND_MATCHED_CONTROL": _rank(wide, ["operating_income", "net_income", "operating_cash_flow"], 2).where(op.gt(0)),
    }
    output: dict[str, pd.DataFrame] = {}
    dates, tickers = context.panels["close"].index, context.panels["close"].columns
    drawdown = context.panels["adj_close"].shift(1).div(context.panels["adj_close"].shift(1).rolling(126, min_periods=126).max()).sub(1)
    for strategy_id, series in raw.items():
        event_date_ticker = series.groupby(level=[0, 1]).last().unstack("ticker").reindex(index=dates, columns=tickers)
        panel = event_date_ticker.ffill(limit=EVENT_HOLD_DAYS)
        if strategy_id == "PROFITABILITY_TURNAROUND_MATCHED_CONTROL":
            panel = panel.where(drawdown.lt(-0.15))
        output[strategy_id] = panel
    return output


def hedged_residual_momentum_score(context: StrategyContext) -> pd.DataFrame:
    market, returns, close = context.market_return, context.daily_returns, context.panels["adj_close"]
    variance = market.rolling(126, min_periods=126).var().shift(1)
    beta = returns.rolling(126, min_periods=126).cov(market).div(variance, axis=0).shift(1)
    residual = returns.sub(beta.mul(market, axis=0)).shift(21).rolling(105, min_periods=105).sum()
    return _orthogonalize(residual, [close.shift(21).div(close.shift(126)).sub(1), close.shift(21).div(close.shift(189)).sub(1)])


def _spy_open_returns(root: Path, dates: pd.DatetimeIndex) -> pd.Series:
    panels = ohlcv_long_to_panels(load_ohlcv_csv(root / PROXY_PATH), value_columns=("open", "high", "low", "close", "volume", "adj_close"))
    spy = build_asset_return_panel(panels["open"], panels["close"], panels["adj_close"], execution_mode="next_open_to_open")["SPY"]
    return spy.reindex(dates)


def _run_hedged(strategy_id: str, score: pd.DataFrame, context: StrategyContext, spy: pd.Series, *, run_id: str, bps: float = 5.0, delay: int = 0):
    spec = StrategySpec(strategy_id, "v3", strategy_id, RATIONALES[strategy_id], lambda _: score, 20, min_cross_section=MIN_CROSS_SECTION)
    eligible = common_eligibility(score, context, spec)
    target, positions = rank_and_weight(score, eligible, spec)
    asset_returns, execution_lag, return_definition = build_execution_returns(context, spec)
    target_beta = target.mul(context.lagged_beta).sum(axis=1)
    hedge = -target_beta.clip(-1.0, 1.0)
    result = compute_portfolio_returns_from_weights(
        target, asset_returns, execution_lag=execution_lag + delay, buy_bps=bps, sell_bps=bps,
        return_definition=return_definition, hedge_weights=hedge, hedge_returns=spy,
        hedge_buy_bps=bps, hedge_sell_bps=bps,
    )
    daily = pd.DataFrame({"date": score.index, "gross_return": result.gross_return, "transaction_cost": result.transaction_cost, "net_return": result.net_return, "turnover": result.turnover, "target_beta": target_beta, "hedge_notional": hedge, "hedge_turnover": result.hedge_turnover, "hedge_transaction_cost": result.hedge_transaction_cost}).dropna(subset=["gross_return", "net_return"]).reset_index(drop=True)
    trades = build_trade_log(strategy_id, target, context.panels["open"], run_id=run_id)
    hedge_rows = []
    valid_dates = set(pd.to_datetime(daily["date"]))
    previous = 0.0
    for date, value in result.hedge_weight.items():
        if date in valid_dates and result.hedge_turnover.loc[date] > 0:
            hedge_rows.append({"strategy_id": strategy_id, "signal_date": date.date().isoformat(), "rebalance_date": date.date().isoformat(), "execution_date": date.date().isoformat(), "ticker": "SPY", "action": "BUY" if value > previous else "SELL", "previous_weight": previous, "target_weight": value, "delta_weight": value-previous, "simulated_execution_price": np.nan, "turnover_contribution": float(result.hedge_turnover.loc[date]), "estimated_transaction_cost": float(result.hedge_transaction_cost.loc[date]), "execution_convention": "NEXT_OPEN_TO_OPEN", "run_id": run_id, "record_status": "SIMULATED | RESEARCH ONLY | NO LIVE FILL | HEDGE"})
        previous = value
    trades = pd.concat([trades, pd.DataFrame(hedge_rows)], ignore_index=True)
    active = target.loc[target.abs().sum(axis=1).gt(0)]
    holdings = pd.DataFrame([{"strategy_id": strategy_id, "date": active.index[-1].date().isoformat(), "ticker": ticker, "side": "LONG" if weight > 0 else "SHORT", "target_weight": weight} for ticker, weight in active.iloc[-1].items() if weight != 0]) if len(active) else pd.DataFrame()
    summary = _summary(strategy_id, daily, eligible)
    summary.update({"trade_cost_reconciliation_error": float(abs(trades["estimated_transaction_cost"].sum()-daily["transaction_cost"].sum())), "average_target_beta": float(target_beta.abs().mean()), "average_hedge_notional": float(hedge.abs().mean()), "total_hedge_turnover": float(result.hedge_turnover.sum()), "total_hedge_transaction_cost": float(result.hedge_transaction_cost.sum()), "realized_beta": float(daily.set_index("date")["net_return"].cov(spy) / spy.var())})
    return daily, holdings, trades, summary


def _classify(row: dict[str, Any]) -> tuple[str, str]:
    checks = [
        ("net return <= 0", row["net_cumulative_return"] > 0), ("OOS return <= 1%", row["preliminary_oos_net_return"] > .01),
        ("Sharpe < 0.25", row["net_sharpe"] >= .25), ("2x-cost return <= 0", row["double_cost_net_return"] > 0),
        ("delayed return <= 0", row["delayed_execution_net_return"] > 0), ("inadequate event/cross-section count", row["average_eligible_count"] >= MIN_CROSS_SECTION),
        ("severe concentration", row["latest_max_abs_weight"] > 0 and row["latest_max_abs_weight"] <= .10),
        ("dominated duplicate", row["maximum_active_correlation"] < .90),
        ("no positive marginal or material tail benefit", row["marginal_combined_portfolio_sharpe"] > 0 or row["marginal_max_drawdown_improvement"] > .005 or row["marginal_left_tail_improvement"] > .0001),
    ]
    blockers = [name for name, passed in checks if not passed]
    if not blockers:
        return "ACTIVE", "Passed every strict challenge gate."
    if row["net_cumulative_return"] <= 0 and row["preliminary_oos_net_return"] <= 0:
        return "ARCHIVED", "; ".join(blockers)
    return "REPAIR", "; ".join(blockers)


def run_event_panel_batch(project_root: str | Path, *, user_agent: str) -> dict[str, Any]:
    root, output = Path(project_root), Path(project_root) / OUTPUT_ROOT
    output.mkdir(parents=True, exist_ok=True)
    context = load_context(root / OHLCV_CACHE)
    signal_dates = context.panels["close"].index[::20]
    membership = diagnostic_broad_membership(signal_dates, context.panels["close"], context.lagged_adv)
    broad_mask = _mask(membership, context.panels["close"].index, context.panels["close"].columns)
    latest = membership.loc[membership["rebalance_date"].eq(signal_dates[-1]) & membership["included"], "ticker"].tolist()
    facts, _, sec_audit = load_expanded_facts(root, latest, user_agent)
    events = build_filing_event_panel(facts, context.panels["close"].index)
    events.to_csv(output / "filing_event_panel.csv", index=False)
    scores = event_scores(events, context)
    scores["HEDGED_RESIDUAL_MOMENTUM_V3"] = hedged_residual_momentum_score(context)
    scores = {key: value.where(broad_mask) for key, value in scores.items()}
    active = _active_returns(root / "dashboard/data/us_equity_research_bundle.json").drop(columns=["ORTHOGONAL_LOW_ACCRUAL_MOMENTUM"], errors="ignore")
    spy = _spy_open_returns(root, context.panels["close"].index)
    run_id = f"{PACK_ID}_{context.panels['close'].index.max().date().isoformat()}"
    summaries, daily_parts, holdings_parts, trade_parts, return_map = [], [], [], [], {}
    for strategy_id in CANDIDATE_IDS:
        score = scores[strategy_id]
        if strategy_id == "HEDGED_RESIDUAL_MOMENTUM_V3":
            daily, holdings, trades, row = _run_hedged(strategy_id, score, context, spy, run_id=run_id)
            double = _run_hedged(strategy_id, score, context, spy, run_id=run_id, bps=10.0)[3]
            delayed = _run_hedged(strategy_id, score, context, spy, run_id=run_id, delay=1)[3]
            row.update({"double_cost_net_return": double["net_cumulative_return"], "delayed_execution_net_return": delayed["net_cumulative_return"], "latest_max_abs_weight": float(holdings["target_weight"].abs().max()) if len(holdings) else np.nan, "latest_weight_hhi": float(holdings["target_weight"].pow(2).sum()) if len(holdings) else np.nan})
        else:
            daily, holdings, trades, row = run_candidate(strategy_id, score, context, run_id=run_id)
            from src.strategies.final_delivery_research import _robustness
            row.update(_robustness(score, context))
        candidate = daily.set_index("date")["net_return"]
        aligned = pd.concat([active, candidate.rename(strategy_id)], axis=1, join="inner")
        corr = aligned.corr().loc[strategy_id, active.columns].abs()
        row.update(_portfolio_value(active, candidate)); row.update(_contribution_diagnostics(score, context))
        row.update({"maximum_active_correlation": float(corr.max()), "average_active_correlation": float(corr.mean()), "highest_active_correlation_strategy": str(corr.idxmax()), "actual_universe_used": "OHLCV_UNIVERSE" if strategy_id == "HEDGED_RESIDUAL_MOMENTUM_V3" else "EXACT_FILING_EVENT_PANEL", "economic_rationale": RATIONALES[strategy_id], "labels": "CURRENT_LISTED_DIAGNOSTIC | SURVIVORSHIP_BIAS_PRESENT | RESEARCH ONLY", "live_allocation_approved": False, "execution_enabled": False})
        row["classification"], row["classification_reason"] = _classify(row)
        summaries.append(row); daily_parts.append(daily.assign(strategy_id=strategy_id)); holdings_parts.append(holdings); trade_parts.append(trades); return_map[strategy_id] = candidate
    pd.DataFrame(summaries).to_csv(output / "candidate_summary.csv", index=False)
    pd.concat(daily_parts, ignore_index=True).to_csv(output / "daily_strategy_returns.csv", index=False)
    pd.concat(holdings_parts, ignore_index=True).to_csv(output / "holdings.csv", index=False)
    pd.concat(trade_parts, ignore_index=True).to_csv(output / "trade_log.csv", index=False)
    returns = pd.DataFrame(return_map); pd.concat([returns, active], axis=1, join="inner").corr().to_csv(output / "correlation_matrix.csv")
    labels, regimes = _market_proxy_regime_labels(root, returns.index), []
    for strategy_id in returns:
        for regime in sorted(labels.dropna().unique()):
            selected = returns.loc[labels.eq(regime), strategy_id].dropna()
            regimes.append({"strategy_id": strategy_id, "regime_id": "MARKET_PROXY_REGIME_V0", "regime": regime, "observations": len(selected), "net_cumulative_return": float(selected.add(1).prod()-1), "net_sharpe": float(sharpe_ratio(selected)), "alters_weights": False})
    pd.DataFrame(regimes).to_csv(output / "market_proxy_regime_v0.csv", index=False)
    (output / "strategy_specification.json").write_text(json.dumps(RATIONALES, indent=2), encoding="utf-8")
    (output / "run_manifest.json").write_text(json.dumps({"pack_id": PACK_ID, "status": "RESEARCH_ONLY", "execution": "NEXT_OPEN_TO_OPEN", "event_hold_days": EVENT_HOLD_DAYS, "event_panel_rows": len(events), "accepted_timestamp_rows": int(events["accepted_datetime"].notna().sum()), "fallback_rows": int(events["accepted_datetime"].isna().sum()), "sec_audit": sec_audit, "labels": ["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT", "RESEARCH ONLY"], "live_allocation_approved": False, "execution_enabled": False, "fill_status": "NO LIVE FILL", "matched_control_label": "CAUSAL_INSPIRED_NOT_CAUSAL_PROOF"}, indent=2), encoding="utf-8")
    return {"output_root": output, "summaries": summaries}
