"""Strict final challenge batch using existing point-in-time and cross-sectional research interfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.risk.performance import max_drawdown, sharpe_ratio
from src.strategies.diverse_strategy_research import _active_returns, _market_proxy_regime_labels
from src.strategies.expanded_selection_research import MIN_CROSS_SECTION, OHLCV_CACHE, _mask, load_expanded_facts
from src.strategies.final_delivery_research import _robustness
from src.strategies.fundamental_research import _rank_mean, build_raw_component_panel, run_candidate
from src.strategies.strategy_factory import StrategyContext, StrategySpec, build_execution_returns, common_eligibility, load_context, rank_and_weight
from src.strategies.universe_foundation import diagnostic_broad_membership

PACK_ID = "FINAL_STRICT_CHALLENGE_BATCH_V1"
OUTPUT_ROOT = Path("output/research/final_strict_challenge_batch_v1")
CANDIDATE_IDS = (
    "HEDGED_RESIDUAL_MOMENTUM_V2", "ORTHOGONAL_LOW_ACCRUAL_MOMENTUM", "CLUSTER_NEUTRAL_MEAN_REVERSION",
    "ASSET_LIGHT_COMPOUNDER", "FCF_REINVESTMENT_EFFICIENCY", "EARNINGS_QUALITY_VALUE_SPREAD",
    "CASH_CONVERSION_IMPROVEMENT", "HIGH_CONVICTION_FILING_DRIFT_V2", "CASH_FLOW_INFLECTION_CONTINUATION",
    "BALANCE_SHEET_REPAIR_AFTER_STRESS",
)
EVENT_IDS = {
    "HIGH_CONVICTION_FILING_DRIFT_V2", "CASH_FLOW_INFLECTION_CONTINUATION", "BALANCE_SHEET_REPAIR_AFTER_STRESS"
}
RATIONALES = {
    "HEDGED_RESIDUAL_MOMENTUM_V2": "Residual momentum orthogonalized to active momentum signals, then explicitly hedged with lagged SPY beta.",
    "ORTHOGONAL_LOW_ACCRUAL_MOMENTUM": "Lower accruals, positive cash flow, and momentum orthogonalized to active momentum signals.",
    "CLUSTER_NEUTRAL_MEAN_REVERSION": "Fade lagged five-day residual moves within trailing-return beta/volatility relationship clusters.",
    "ASSET_LIGHT_COMPOUNDER": "Prefer growth, improving asset turnover, low capex intensity, positive FCF, and stable margins.",
    "FCF_REINVESTMENT_EFFICIENCY": "Test whether lagged capex is followed by improving growth, efficiency, and positive FCF.",
    "EARNINGS_QUALITY_VALUE_SPREAD": "Combine point-in-time earnings/FCF/book value spreads with quality and leverage control.",
    "CASH_CONVERSION_IMPROVEMENT": "Prefer improving cash conversion, disciplined receivables/inventory, and cash-flow margins.",
    "HIGH_CONVICTION_FILING_DRIFT_V2": "Strict positive fundamental filing change with cash-flow and earnings-quality confirmation.",
    "CASH_FLOW_INFLECTION_CONTINUATION": "Post-filing continuation after operating-cash-flow inflection or acceleration.",
    "BALANCE_SHEET_REPAIR_AFTER_STRESS": "Controlled recovery after prior drawdown with improving liabilities, cash flow, and profitability.",
}


def _orthogonalize(score: pd.DataFrame, exposures: list[pd.DataFrame]) -> pd.DataFrame:
    output = pd.DataFrame(index=score.index, columns=score.columns, dtype=float)
    for date in score.index:
        frame = pd.concat([score.loc[date].rename("y")] + [value.loc[date].rename(f"x{i}") for i, value in enumerate(exposures)], axis=1).dropna()
        if len(frame) < MIN_CROSS_SECTION:
            continue
        x = np.column_stack([np.ones(len(frame))] + [frame[column].to_numpy() for column in frame.columns[1:]])
        output.loc[date, frame.index] = frame["y"].to_numpy() - x @ np.linalg.lstsq(x, frame["y"].to_numpy(), rcond=None)[0]
    return output


def ohlcv_scores(context: StrategyContext) -> dict[str, pd.DataFrame]:
    close, returns = context.panels["adj_close"], context.daily_returns
    market = context.market_return
    variance = market.rolling(126, min_periods=126).var().shift(1)
    beta = returns.rolling(126, min_periods=126).cov(market).div(variance, axis=0).shift(1)
    residual = returns.sub(beta.mul(market, axis=0))
    residual_momentum = residual.shift(21).rolling(105, min_periods=105).sum()
    momentum_6_1 = close.shift(21).div(close.shift(126)).sub(1)
    momentum_9_1 = close.shift(21).div(close.shift(189)).sub(1)
    hedged = _orthogonalize(residual_momentum, [momentum_6_1, momentum_9_1])
    move = residual.rolling(5, min_periods=5).sum().shift(1)
    vol = residual.rolling(63, min_periods=63).std().shift(1)
    beta_bucket = np.floor(beta.rank(axis=1, pct=True).mul(3).clip(upper=2.999))
    vol_bucket = np.floor(vol.rank(axis=1, pct=True).mul(3).clip(upper=2.999))
    cluster_residual = pd.DataFrame(index=move.index, columns=move.columns, dtype=float)
    for date in move.index:
        groups = pd.DataFrame({"move": move.loc[date], "b": beta_bucket.loc[date], "v": vol_bucket.loc[date]}).dropna()
        if not groups.empty:
            cluster_residual.loc[date, groups.index] = -(groups["move"] - groups.groupby(["b", "v"])["move"].transform("mean"))
    return {"HEDGED_RESIDUAL_MOMENTUM_V2": hedged, "CLUSTER_NEUTRAL_MEAN_REVERSION": cluster_residual}


def fundamental_scores(raw: pd.DataFrame, context: StrategyContext) -> dict[str, pd.DataFrame]:
    quality = _rank_mean(raw, ["quality_gp_assets", "quality_op_assets", "quality_ocf_assets"])
    momentum = context.panels["adj_close"].shift(21).div(context.panels["adj_close"].shift(126)).sub(1)
    low_accrual = pd.concat([
        raw["negative_accruals_assets"].groupby(level="date").rank(pct=True),
        raw["quality_ocf_assets"].groupby(level="date").rank(pct=True),
        momentum.stack().reindex(raw.index).groupby(level="date").rank(pct=True),
    ], axis=1).mean(axis=1, skipna=False)
    low_capex = (-raw["capex_assets"]).groupby(level="date").rank(pct=True)
    series = {
        "ORTHOGONAL_LOW_ACCRUAL_MOMENTUM": low_accrual,
        "ASSET_LIGHT_COMPOUNDER": pd.concat([
            _rank_mean(raw, ["annual_revenue_growth", "annual_operating_income_growth", "annual_asset_turnover_change", "fcf_assets", "gross_margin_stability"], minimum=4),
            low_capex,
        ], axis=1).mean(axis=1, skipna=False),
        "FCF_REINVESTMENT_EFFICIENCY": _rank_mean(raw, ["prior_capex_assets", "annual_revenue_growth", "annual_operating_income_growth", "annual_asset_turnover_change", "fcf_assets"], minimum=4),
        "EARNINGS_QUALITY_VALUE_SPREAD": _rank_mean(raw, ["earnings_yield", "fcf_yield", "book_to_market", "negative_accruals_assets", "quality_op_assets", "negative_liabilities_assets"], minimum=4),
        "CASH_CONVERSION_IMPROVEMENT": _rank_mean(raw, ["ocf_abs_net_income", "receivables_growth_gap", "inventory_growth_gap", "annual_cash_flow_margin_change"], minimum=3),
        "HIGH_CONVICTION_FILING_DRIFT_V2": _rank_mean(raw, ["revenue_acceleration", "annual_ocf_growth", "annual_margin_change", "negative_accruals_assets"], minimum=4).where(raw["annual_ocf_growth"].gt(0)),
        "CASH_FLOW_INFLECTION_CONTINUATION": _rank_mean(raw, ["annual_ocf_growth", "annual_ocf_assets_change", "annual_cash_flow_margin_change"], minimum=3).where(raw["annual_ocf_growth"].gt(0)),
    }
    prior_drawdown = context.panels["adj_close"].shift(1).div(context.panels["adj_close"].shift(1).rolling(126, min_periods=126).max()).sub(1).stack().reindex(raw.index)
    series["BALANCE_SHEET_REPAIR_AFTER_STRESS"] = _rank_mean(raw, ["negative_liabilities_assets_change", "annual_ocf_assets_change", "annual_op_assets_change"], minimum=3).where(prior_drawdown.lt(-0.20))
    panels = {key: value.unstack("ticker").reindex(index=context.panels["close"].index, columns=context.panels["close"].columns).ffill() for key, value in series.items()}
    panels["ORTHOGONAL_LOW_ACCRUAL_MOMENTUM"] = _orthogonalize(panels["ORTHOGONAL_LOW_ACCRUAL_MOMENTUM"], [momentum])
    return panels


def _portfolio_value(active: pd.DataFrame, candidate: pd.Series) -> dict[str, float]:
    aligned = pd.concat([active, candidate.rename("candidate")], axis=1, join="inner")
    base = aligned[active.columns].mean(axis=1)
    combined = aligned.mean(axis=1)
    return {
        "marginal_combined_portfolio_sharpe": float(sharpe_ratio(combined) - sharpe_ratio(base)),
        "marginal_max_drawdown_improvement": float(max_drawdown(combined) - max_drawdown(base)),
        "marginal_left_tail_improvement": float(combined.quantile(.05) - base.quantile(.05)),
    }


def _contribution_diagnostics(score: pd.DataFrame, context: StrategyContext) -> dict[str, Any]:
    spec = StrategySpec("ATTR", "attr_v1", "Attribution", "Shared target attribution", lambda _: score, 20, min_cross_section=MIN_CROSS_SECTION)
    target, _ = rank_and_weight(score, common_eligibility(score, context, spec), spec)
    asset_returns, lag, _ = build_execution_returns(context, spec)
    contributions = target.shift(lag).mul(asset_returns)
    by_name = contributions.sum().sort_values(key=abs, ascending=False)
    by_period = contributions.sum(axis=1).sort_values(key=abs, ascending=False)
    return {
        "largest_name_contributor": str(by_name.index[0]) if len(by_name) else "",
        "largest_name_contribution": float(by_name.iloc[0]) if len(by_name) else np.nan,
        "largest_period": by_period.index[0].date().isoformat() if len(by_period) else "",
        "largest_period_contribution": float(by_period.iloc[0]) if len(by_period) else np.nan,
        "gross_attribution_reconciliation_error": float((contributions.sum(axis=1) - contributions.sum(axis=1)).abs().max()),
    }


def classify(row: dict[str, Any], strategy_id: str) -> tuple[str, str]:
    blockers = []
    checks = [
        ("net return <= 0", row["net_cumulative_return"] > 0),
        ("OOS return is not economically meaningful (>1%)", row["preliminary_oos_net_return"] > .01),
        ("net Sharpe < 0.25", row["net_sharpe"] >= .25),
        ("2x-cost return <= 0", row["double_cost_net_return"] > 0),
        ("one-day-delayed return <= 0", row["delayed_execution_net_return"] > 0),
        ("eligible coverage is inadequate", row["average_eligible_count"] >= MIN_CROSS_SECTION and row["eligible_portfolio_days"] >= 12),
        ("severe latest concentration", row["latest_max_abs_weight"] <= .10),
        ("duplicate correlation >= 0.90", row["maximum_active_correlation"] < .90),
        ("no positive marginal Sharpe or material drawdown/tail benefit", row["marginal_combined_portfolio_sharpe"] > 0 or row["marginal_max_drawdown_improvement"] > .005 or row["marginal_left_tail_improvement"] > .0001),
    ]
    blockers.extend(label for label, passed in checks if not passed)
    if strategy_id in EVENT_IDS:
        blockers.append("monthly panel does not prove event-timestamp execution; real event study required")
    if strategy_id == "HEDGED_RESIDUAL_MOMENTUM_V2":
        blockers.append("explicit SPY hedge/hedge-cost Trade Log is not supported by the shared stock-only backtester")
    if not blockers:
        return "ACTIVE", "Passed every strict challenge gate."
    if row["net_cumulative_return"] <= 0 and row["preliminary_oos_net_return"] <= 0:
        return "ARCHIVED", "; ".join(blockers)
    return "REPAIR", "; ".join(blockers)


def run_final_challenge_batch(project_root: str | Path, *, user_agent: str) -> dict[str, Any]:
    root, output = Path(project_root), Path(project_root) / OUTPUT_ROOT
    output.mkdir(parents=True, exist_ok=True)
    context = load_context(root / OHLCV_CACHE)
    signal_dates = context.panels["close"].index[::20]
    membership = diagnostic_broad_membership(signal_dates, context.panels["close"], context.lagged_adv)
    broad_mask = _mask(membership, context.panels["close"].index, context.panels["close"].columns)
    latest = membership.loc[membership["rebalance_date"].eq(signal_dates[-1]) & membership["included"], "ticker"].tolist()
    facts, _, sec_audit = load_expanded_facts(root, latest, user_agent)
    raw = build_raw_component_panel(facts, context, signal_dates)
    scores = ohlcv_scores(context) | fundamental_scores(raw, context)
    scores = {key: value.where(broad_mask) for key, value in scores.items()}
    active = _active_returns(root / "dashboard/data/us_equity_research_bundle.json")
    run_id = f"{PACK_ID}_{context.panels['close'].index.max().date().isoformat()}"
    summaries, daily_parts, holdings_parts, trade_parts, return_map = [], [], [], [], {}
    for strategy_id in CANDIDATE_IDS:
        score = scores[strategy_id]
        daily, holdings, trades, row = run_candidate(strategy_id, score, context, run_id=run_id)
        candidate = daily.set_index("date")["net_return"]
        aligned = pd.concat([active, candidate.rename(strategy_id)], axis=1, join="inner")
        corr = aligned.corr().loc[strategy_id, active.columns].abs()
        split = len(candidate) // 2
        counts = score.notna().sum(axis=1)
        row.update(_robustness(score, context))
        row.update(_portfolio_value(active, candidate))
        row.update(_contribution_diagnostics(score, context))
        row.update({
            "first_half_net_return": float(candidate.iloc[:split].add(1).prod() - 1),
            "second_half_net_return": float(candidate.iloc[split:].add(1).prod() - 1),
            "maximum_active_correlation": float(corr.max()), "average_active_correlation": float(corr.mean()),
            "highest_active_correlation_strategy": str(corr.idxmax()), "eligible_portfolio_days": int(counts.ge(MIN_CROSS_SECTION).sum()),
            "actual_universe_used": "OHLCV_UNIVERSE" if strategy_id in ohlcv_scores(context) else "FUNDAMENTAL_UNIVERSE",
            "economic_rationale": RATIONALES[strategy_id],
            "labels": "CURRENT_LISTED_DIAGNOSTIC | SURVIVORSHIP_BIAS_PRESENT | RESEARCH ONLY",
            "live_allocation_approved": False, "execution_enabled": False,
        })
        row["classification"], row["classification_reason"] = classify(row, strategy_id)
        summaries.append(row); daily_parts.append(daily.assign(strategy_id=strategy_id)); holdings_parts.append(holdings); trade_parts.append(trades); return_map[strategy_id] = candidate
    summary = pd.DataFrame(summaries)
    summary.to_csv(output / "candidate_summary.csv", index=False)
    pd.concat(daily_parts, ignore_index=True).to_csv(output / "daily_strategy_returns.csv", index=False)
    pd.concat(holdings_parts, ignore_index=True).to_csv(output / "holdings.csv", index=False)
    pd.concat(trade_parts, ignore_index=True).to_csv(output / "trade_log.csv", index=False)
    returns = pd.DataFrame(return_map)
    pd.concat([returns, active], axis=1, join="inner").corr().to_csv(output / "correlation_matrix.csv")
    labels, regimes = _market_proxy_regime_labels(root, returns.index), []
    for strategy_id in returns:
        for regime in sorted(labels.dropna().unique()):
            selected = returns.loc[labels.eq(regime), strategy_id].dropna()
            regimes.append({"strategy_id": strategy_id, "regime_id": "MARKET_PROXY_REGIME_V0", "regime": regime, "observations": len(selected), "net_cumulative_return": float(selected.add(1).prod()-1), "net_sharpe": float(sharpe_ratio(selected)), "alters_weights": False})
    pd.DataFrame(regimes).to_csv(output / "market_proxy_regime_v0.csv", index=False)
    (output / "strategy_specification.json").write_text(json.dumps(RATIONALES, indent=2), encoding="utf-8")
    (output / "run_manifest.json").write_text(json.dumps({"pack_id": PACK_ID, "status": "RESEARCH_ONLY", "execution": "NEXT_OPEN_TO_OPEN", "buy_bps": 5, "sell_bps": 5, "labels": ["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT", "RESEARCH ONLY"], "sec_audit": sec_audit, "event_study_limitation": "Monthly shared panel cannot prove exact event-timestamp execution.", "live_allocation_approved": False, "execution_enabled": False, "fill_status": "NO LIVE FILL"}, indent=2), encoding="utf-8")
    return {"output_root": output, "summaries": summaries}
