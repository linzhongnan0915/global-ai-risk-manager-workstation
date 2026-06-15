"""Final diversified OHLCV, point-in-time fundamental, and filing diagnostic batch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.risk.performance import max_drawdown, sharpe_ratio
from src.strategies.diverse_strategy_research import _active_returns, _market_proxy_regime_labels, combine_components
from src.strategies.expanded_selection_research import MIN_CROSS_SECTION, OHLCV_CACHE, _mask, load_expanded_facts
from src.strategies.final_delivery_research import _robustness
from src.strategies.fundamental_research import _rank_mean, build_raw_component_panel, run_candidate
from src.strategies.strategy_factory import StrategyContext, load_context
from src.strategies.universe_foundation import diagnostic_broad_membership

PACK_ID = "FINAL_DIVERSIFIED_STRATEGY_BATCH_V1"
OUTPUT_ROOT = Path("output/research/final_diversified_strategy_batch_v1")

CANDIDATE_IDS = (
    "BETA_NEUTRAL_RESIDUAL_MOMENTUM", "BETA_NEUTRAL_SHORT_TERM_REVERSAL",
    "LOW_VOLATILITY_TREND_CARRY", "VOLUME_CONFIRMED_GAP_CONTINUATION",
    "CASH_RETURN_ON_ASSETS", "FREE_CASH_FLOW_PROFITABILITY", "GROSS_MARGIN_STABILITY",
    "DEBT_PAYDOWN_PROFITABILITY", "WORKING_CAPITAL_DISCIPLINE",
    "QUALITY_FILTERED_FILING_DRIFT", "NEGATIVE_FILING_SHOCK_REVERSAL",
    "BALANCED_FUNDAMENTAL_MULTIFACTOR",
)

RATIONALES = {
    "BETA_NEUTRAL_RESIDUAL_MOMENTUM": "Rank medium-term momentum after removing the lagged broad-market component.",
    "BETA_NEUTRAL_SHORT_TERM_REVERSAL": "Fade short-term residual returns after removing broad-market movement.",
    "LOW_VOLATILITY_TREND_CARRY": "Prefer positive medium-term trend with lower realized and downside volatility.",
    "VOLUME_CONFIRMED_GAP_CONTINUATION": "Follow sufficiently large prior gaps confirmed by abnormal volume and prior trend.",
    "CASH_RETURN_ON_ASSETS": "Prefer positive operating cash flow and free cash flow relative to assets.",
    "FREE_CASH_FLOW_PROFITABILITY": "Prefer free-cash-flow margin and FCF/assets with operating-profitability confirmation.",
    "GROSS_MARGIN_STABILITY": "Prefer positive, stable gross margins without deteriorating operating cash flow.",
    "DEBT_PAYDOWN_PROFITABILITY": "Prefer declining liabilities/assets with positive operating income and cash flow.",
    "WORKING_CAPITAL_DISCIPLINE": "Prefer receivables and inventory growth that does not exceed revenue growth.",
    "QUALITY_FILTERED_FILING_DRIFT": "Continue positive filing improvements only when cash-flow and earnings quality confirm.",
    "NEGATIVE_FILING_SHOCK_REVERSAL": "Test controlled recovery after negative filing shocks when cash-flow and balance-sheet resilience remain.",
    "BALANCED_FUNDAMENTAL_MULTIFACTOR": "Combine normalized fundamental momentum, earnings quality, margin improvement, cash return, and lower leverage before construction.",
}


def ohlcv_scores(context: StrategyContext) -> dict[str, pd.DataFrame]:
    returns, close = context.daily_returns, context.panels["adj_close"]
    market = context.market_return
    variance = market.rolling(126, min_periods=126).var().shift(1)
    beta = returns.rolling(126, min_periods=126).cov(market).div(variance, axis=0).shift(1)
    residual = returns.sub(beta.mul(market, axis=0))
    residual_momentum = residual.shift(21).rolling(105, min_periods=105).sum()
    residual_reversal = -residual.rolling(5, min_periods=5).sum().shift(1)
    trend = close.shift(21).div(close.shift(126)).sub(1)
    vol = returns.rolling(63, min_periods=63).std().shift(1).replace(0, np.nan)
    downside = returns.clip(upper=0).pow(2).rolling(126, min_periods=126).mean().pow(0.5).shift(1)
    gap = context.panels["open"].shift(1).div(context.panels["close"].shift(2)).sub(1)
    volume = context.panels["volume"]
    volume_z = volume.shift(1).sub(volume.shift(1).rolling(63, min_periods=63).mean()).div(
        volume.shift(1).rolling(63, min_periods=63).std().replace(0, np.nan)
    )
    return {
        "BETA_NEUTRAL_RESIDUAL_MOMENTUM": residual_momentum,
        "BETA_NEUTRAL_SHORT_TERM_REVERSAL": residual_reversal,
        "LOW_VOLATILITY_TREND_CARRY": combine_components([trend.div(vol), -vol, -downside], [0.5, 0.25, 0.25]).where(trend.gt(0)),
        "VOLUME_CONFIRMED_GAP_CONTINUATION": gap.mul(volume_z.clip(lower=0)).where(gap.abs().ge(0.015) & volume_z.gt(1) & trend.mul(gap).gt(0)),
    }


def fundamental_scores(raw: pd.DataFrame, context: StrategyContext) -> dict[str, pd.DataFrame]:
    quality = _rank_mean(raw, ["quality_gp_assets", "quality_op_assets", "quality_ocf_assets"])
    earnings_quality = _rank_mean(raw, ["negative_accruals_assets", "ocf_revenue", "ocf_abs_net_income"])
    fundamental_momentum = _rank_mean(raw, ["annual_revenue_growth", "annual_margin_change", "annual_ocf_assets_change"])
    margin_improvement = _rank_mean(raw, ["annual_margin_change", "annual_cash_flow_margin_change"])
    cash_return = _rank_mean(raw, ["quality_ocf_assets", "fcf_assets"]).where(raw["quality_ocf_assets"].gt(0))
    free_cash_flow = _rank_mean(raw, ["fcf_assets", "ocf_revenue", "quality_op_assets"]).where(raw["fcf_assets"].gt(0) & raw["quality_op_assets"].gt(0))
    gross_stability = _rank_mean(raw, ["gross_margin", "gross_margin_stability", "annual_ocf_assets_change"]).where(raw["gross_margin"].gt(0) & raw["annual_ocf_assets_change"].ge(0))
    debt_paydown = _rank_mean(raw, ["negative_liabilities_assets_change", "quality_op_assets", "quality_ocf_assets"]).where(raw["quality_op_assets"].gt(0) & raw["quality_ocf_assets"].gt(0))
    working_capital = _rank_mean(raw, ["receivables_growth_gap", "inventory_growth_gap"], minimum=2)
    filing_shock = _rank_mean(raw, ["revenue_acceleration", "annual_ocf_growth", "annual_margin_change"])
    filing_drift = pd.concat([filing_shock, earnings_quality], axis=1).mean(axis=1, skipna=False).where(raw["annual_ocf_growth"].gt(0))
    resilience = _rank_mean(raw, ["quality_ocf_assets", "negative_liabilities_assets", "negative_accruals_assets"])
    prior_return = context.panels["adj_close"].shift(1).div(context.panels["adj_close"].shift(21)).sub(1).stack().reindex(raw.index)
    shock_reversal = (-filing_shock).mul((-prior_return).clip(lower=0)).where(resilience.gt(0.5))
    balanced = pd.concat([fundamental_momentum, earnings_quality, margin_improvement, cash_return, raw["negative_liabilities_assets"].groupby(level="date").rank(pct=True)], axis=1).mean(axis=1, skipna=False)
    series = {
        "CASH_RETURN_ON_ASSETS": cash_return, "FREE_CASH_FLOW_PROFITABILITY": free_cash_flow,
        "GROSS_MARGIN_STABILITY": gross_stability, "DEBT_PAYDOWN_PROFITABILITY": debt_paydown,
        "WORKING_CAPITAL_DISCIPLINE": working_capital, "QUALITY_FILTERED_FILING_DRIFT": filing_drift,
        "NEGATIVE_FILING_SHOCK_REVERSAL": shock_reversal, "BALANCED_FUNDAMENTAL_MULTIFACTOR": balanced,
    }
    return {key: value.unstack("ticker").reindex(index=context.panels["close"].index, columns=context.panels["close"].columns).ffill() for key, value in series.items()}


def _portfolio_improvements(active: pd.DataFrame, candidate: pd.Series) -> dict[str, float]:
    base = active.mean(axis=1).dropna()
    aligned = pd.concat([active, candidate.rename("candidate")], axis=1, join="inner")
    combined = aligned.mean(axis=1)
    return {
        "marginal_combined_portfolio_sharpe": float(sharpe_ratio(combined) - sharpe_ratio(base.reindex(combined.index))),
        "marginal_max_drawdown_improvement": float(max_drawdown(combined) - max_drawdown(base.reindex(combined.index))),
        "marginal_left_tail_improvement": float(combined.quantile(0.05) - base.reindex(combined.index).quantile(0.05)),
    }


def classify(row: dict[str, Any]) -> tuple[str, str]:
    if row["average_eligible_count"] < MIN_CROSS_SECTION or row["eligible_portfolio_days"] < 12:
        return "DATA_INSUFFICIENT", "Eligible cross-section is below the minimum diagnostic threshold."
    portfolio_value = row["marginal_combined_portfolio_sharpe"] > 0 or row["marginal_max_drawdown_improvement"] > 0.005 or row["marginal_left_tail_improvement"] > 0.0001
    gates = (
        row["net_cumulative_return"] > 0, row["preliminary_oos_net_return"] > 0,
        row["net_sharpe"] >= 0.25 or row["marginal_max_drawdown_improvement"] > 0.005,
        row["double_cost_net_return"] > 0, row["delayed_execution_net_return"] > 0,
        row["maximum_active_correlation"] < 0.90, portfolio_value,
    )
    if all(gates):
        return "ACTIVE", "Passed standalone, robustness, coverage, duplication, and portfolio-value gates."
    if row["net_cumulative_return"] <= 0 and row["preliminary_oos_net_return"] <= 0:
        return "ARCHIVED", "Full-period and preliminary OOS returns are both non-positive."
    return "REPAIR", "One or more final acceptance gates failed."


def run_final_diversified_batch(project_root: str | Path, *, user_agent: str) -> dict[str, Any]:
    root, output = Path(project_root), Path(project_root) / OUTPUT_ROOT
    output.mkdir(parents=True, exist_ok=True)
    context = load_context(root / OHLCV_CACHE)
    signal_dates = context.panels["close"].index[::20]
    broad = diagnostic_broad_membership(signal_dates, context.panels["close"], context.lagged_adv)
    broad_mask = _mask(broad, context.panels["close"].index, context.panels["close"].columns)
    latest = broad.loc[broad["rebalance_date"].eq(signal_dates[-1]) & broad["included"], "ticker"].tolist()
    facts, _, sec_audit = load_expanded_facts(root, latest, user_agent)
    raw = build_raw_component_panel(facts, context, signal_dates)
    scores = ohlcv_scores(context) | fundamental_scores(raw, context)
    scores = {key: value.where(broad_mask) for key, value in scores.items()}
    active = _active_returns(root / "dashboard/data/us_equity_research_bundle.json")
    run_id = f"{PACK_ID}_{context.panels['close'].index.max().date().isoformat()}"
    summaries, daily_parts, holdings_parts, trade_parts, returns = [], [], [], [], {}
    for strategy_id in CANDIDATE_IDS:
        score = scores[strategy_id]
        daily, holdings, trades, row = run_candidate(strategy_id, score, context, run_id=run_id)
        candidate = daily.set_index("date")["net_return"]
        aligned = pd.concat([active, candidate.rename(strategy_id)], axis=1, join="inner")
        corr = aligned.corr().loc[strategy_id, active.columns].abs()
        row.update(_robustness(score, context))
        row.update(_portfolio_improvements(active, candidate))
        counts = score.notna().sum(axis=1)
        row.update({
            "maximum_active_correlation": float(corr.max()), "average_active_correlation": float(corr.mean()),
            "highest_active_correlation_strategy": str(corr.idxmax()), "eligible_portfolio_days": int(counts.ge(MIN_CROSS_SECTION).sum()),
            "minimum_eligible_count": int(counts.loc[counts.ge(MIN_CROSS_SECTION)].min()) if counts.ge(MIN_CROSS_SECTION).any() else 0,
            "actual_universe_used": "OHLCV_UNIVERSE" if strategy_id in tuple(ohlcv_scores(context)) else "FUNDAMENTAL_UNIVERSE",
            "economic_rationale": RATIONALES[strategy_id], "labels": "CURRENT_LISTED_DIAGNOSTIC | SURVIVORSHIP_BIAS_PRESENT | RESEARCH ONLY",
            "live_allocation_approved": False, "execution_enabled": False,
        })
        if not holdings.empty:
            latest_holdings = holdings.loc[holdings["date"].eq(holdings["date"].max())]
            beta_date = pd.Timestamp(latest_holdings["date"].iloc[0])
            row["latest_estimated_market_beta_exposure"] = float(sum(
                holding.target_weight * context.lagged_beta.loc[beta_date, holding.ticker]
                for holding in latest_holdings.itertuples() if pd.notna(context.lagged_beta.loc[beta_date, holding.ticker])
            ))
        else:
            row["latest_estimated_market_beta_exposure"] = np.nan
        row["classification"], row["classification_reason"] = classify(row)
        summaries.append(row); daily_parts.append(daily.assign(strategy_id=strategy_id)); holdings_parts.append(holdings); trade_parts.append(trades); returns[strategy_id] = candidate
    pd.DataFrame(summaries).to_csv(output / "candidate_summary.csv", index=False)
    pd.concat(daily_parts, ignore_index=True).to_csv(output / "daily_strategy_returns.csv", index=False)
    pd.concat(holdings_parts, ignore_index=True).to_csv(output / "holdings.csv", index=False)
    pd.concat(trade_parts, ignore_index=True).to_csv(output / "trade_log.csv", index=False)
    return_panel = pd.DataFrame(returns); pd.concat([return_panel, active], axis=1, join="inner").corr().to_csv(output / "correlation_matrix.csv")
    regimes, labels = [], _market_proxy_regime_labels(root, return_panel.index)
    for strategy_id in return_panel:
        for regime in sorted(labels.dropna().unique()):
            selected = return_panel.loc[labels.eq(regime), strategy_id].dropna()
            regimes.append({"strategy_id": strategy_id, "regime_id": "MARKET_PROXY_REGIME_V0", "regime": regime, "observations": len(selected), "net_cumulative_return": float(selected.add(1).prod()-1), "net_sharpe": float(sharpe_ratio(selected)), "alters_weights": False})
    pd.DataFrame(regimes).to_csv(output / "market_proxy_regime_v0.csv", index=False)
    (output / "strategy_specification.json").write_text(json.dumps(RATIONALES, indent=2), encoding="utf-8")
    (output / "run_manifest.json").write_text(json.dumps({"pack_id": PACK_ID, "status": "RESEARCH_ONLY", "execution": "NEXT_OPEN_TO_OPEN", "buy_bps": 5, "sell_bps": 5, "labels": ["CURRENT_LISTED_DIAGNOSTIC","SURVIVORSHIP_BIAS_PRESENT","RESEARCH ONLY"], "sec_audit": sec_audit, "live_allocation_approved": False, "execution_enabled": False, "fill_status": "NO LIVE FILL"}, indent=2), encoding="utf-8")
    return {"output_root": output, "summaries": summaries}
