"""Final compact diagnostic research and platform-delivery candidate pack."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.risk.performance import max_drawdown, sharpe_ratio
from src.strategies.c3a1_signals import (
    downside_beta,
    low_rolling_drawdown,
    relative_strength_6_1,
)
from src.strategies.diverse_strategy_research import (
    _active_returns,
    _ensemble_scores,
    _load_facts,
    _market_proxy_regime_labels,
    combine_components,
    matched_control_recovery_score,
)
from src.strategies.fundamental_research import (
    OHLCV_CACHE,
    _rank_mean,
    build_raw_component_panel,
    run_candidate,
)
from src.strategies.strategy_factory import (
    StrategyContext,
    StrategySpec,
    build_execution_returns,
    common_eligibility,
    load_context,
    rank_and_weight,
)
from src.strategies.worldquant.portfolio_returns import compute_portfolio_returns_from_weights

PACK_ID = "FINAL_PLATFORM_DELIVERY_RESEARCH_V1"
OUTPUT_ROOT = Path("output/research/final_platform_delivery_v1")
MIN_CROSS_SECTION = 20

CANDIDATE_SPECS = {
    "OVERNIGHT_INTRADAY_ENSEMBLE": "Overnight and prior-intraday reversal ensemble.",
    "FILING_SHOCK_CONTINUATION": "Continuation after point-in-time filing improvement.",
    "FUNDAMENTAL_SHOCK_RECOVERY": "Matched-control, causal-inspired fundamental shock recovery diagnostic.",
    "CROSS_SECTIONAL_DISPERSION_REVERSAL": "Fade relative five-day extremes only after unusually high cross-sectional dispersion.",
    "LIQUIDITY_SHOCK_RECOVERY": "Fade abnormal declines accompanied by abnormal volume shocks.",
    "VOLATILITY_SCALED_TREND": "Medium-term trend scaled by prior realized volatility.",
    "DOWNSIDE_RESILIENT_MOMENTUM": "Momentum combined with lower downside beta and smaller prior drawdown.",
    "REVENUE_ACCELERATION_QUALITY": "Point-in-time revenue acceleration with positive quality controls.",
    "CASH_FLOW_GROWTH_QUALITY": "Point-in-time cash-flow growth, margin improvement, and earnings quality.",
    "OPERATING_EFFICIENCY_IMPROVEMENT": "Point-in-time operating-margin, asset-turnover, and operating-return improvement.",
    "DELEVERAGING_PROFITABILITY": "Improving profitability with declining debt ratios.",
}

IMPLEMENTABLE_IDS = tuple(strategy_id for strategy_id in CANDIDATE_SPECS if strategy_id != "DELEVERAGING_PROFITABILITY")


def ohlcv_candidate_scores(context: StrategyContext) -> dict[str, pd.DataFrame]:
    returns_5d = context.panels["adj_close"].shift(1).div(context.panels["adj_close"].shift(6)).sub(1.0)
    dispersion = returns_5d.std(axis=1)
    high_dispersion = dispersion.gt(dispersion.rolling(252, min_periods=126).quantile(0.75))
    volume = context.panels["volume"]
    volume_z = volume.shift(1).sub(volume.shift(1).rolling(63, min_periods=63).mean()).div(
        volume.shift(1).rolling(63, min_periods=63).std().replace(0, np.nan)
    )
    decline = -returns_5d
    trend = relative_strength_6_1(context)
    vol = context.daily_returns.rolling(63, min_periods=63).std().shift(1).replace(0, np.nan)
    return {
        "CROSS_SECTIONAL_DISPERSION_REVERSAL": (-returns_5d).where(high_dispersion, np.nan),
        "LIQUIDITY_SHOCK_RECOVERY": combine_components([decline, volume_z], [0.65, 0.35]).where(
            returns_5d.lt(0) & volume_z.gt(0)
        ),
        "VOLATILITY_SCALED_TREND": trend.div(vol).clip(-25, 25),
        "DOWNSIDE_RESILIENT_MOMENTUM": combine_components(
            [trend, downside_beta(context), low_rolling_drawdown(context)], [0.5, 0.25, 0.25]
        ),
    }


def fundamental_candidate_scores(
    raw: pd.DataFrame, dates: pd.DatetimeIndex, tickers: pd.Index
) -> dict[str, pd.DataFrame]:
    quality = _rank_mean(raw, ["quality_gp_assets", "quality_op_assets", "quality_ocf_assets"])
    earnings_quality = _rank_mean(raw, ["negative_accruals_assets", "ocf_revenue", "ocf_abs_net_income"])
    series = {
        "REVENUE_ACCELERATION_QUALITY": pd.concat(
            [raw["revenue_acceleration"].groupby(level="date").rank(pct=True), quality], axis=1
        ).mean(axis=1, skipna=False),
        "CASH_FLOW_GROWTH_QUALITY": pd.concat(
            [
                raw["annual_ocf_growth"].groupby(level="date").rank(pct=True),
                raw["annual_cash_flow_margin_change"].groupby(level="date").rank(pct=True),
                earnings_quality,
            ],
            axis=1,
        ).mean(axis=1, skipna=False),
        "OPERATING_EFFICIENCY_IMPROVEMENT": _rank_mean(
            raw, ["annual_margin_change", "annual_asset_turnover_change", "annual_ocf_assets_change"]
        ),
    }
    return {
        strategy_id: score.unstack("ticker").reindex(index=dates, columns=tickers).ffill()
        for strategy_id, score in series.items()
    }


def _robustness(score: pd.DataFrame, context: StrategyContext) -> dict[str, float]:
    spec = StrategySpec(
        "ROBUSTNESS", "robustness_v1", "Robustness", "Frozen candidate robustness",
        lambda _: score, 20, min_cross_section=MIN_CROSS_SECTION,
    )
    eligible = common_eligibility(score, context, spec)
    target, _ = rank_and_weight(score, eligible, spec)
    asset_returns, execution_lag, return_definition = build_execution_returns(context, spec)

    def result(bps: float, lag: int):
        return compute_portfolio_returns_from_weights(
            target, asset_returns, execution_lag=lag, buy_bps=bps, sell_bps=bps,
            return_definition=return_definition,
        )

    doubled = result(10.0, execution_lag)
    delayed = result(5.0, execution_lag + 1)
    latest = target.loc[target.abs().sum(axis=1).gt(0)].iloc[-1] if target.abs().sum(axis=1).gt(0).any() else pd.Series(dtype=float)
    return {
        "double_cost_net_return": float(doubled.net_return.dropna().add(1).prod() - 1),
        "double_cost_sharpe": float(sharpe_ratio(doubled.net_return.dropna())),
        "delayed_execution_net_return": float(delayed.net_return.dropna().add(1).prod() - 1),
        "delayed_execution_sharpe": float(sharpe_ratio(delayed.net_return.dropna())),
        "latest_max_abs_weight": float(latest.abs().max()) if not latest.empty else np.nan,
        "latest_weight_hhi": float(latest.pow(2).sum()) if not latest.empty else np.nan,
    }


def _classification(row: dict[str, object]) -> tuple[str, str]:
    if row["average_eligible_count"] < MIN_CROSS_SECTION or row["annualized_turnover"] == 0:
        return "DATA_INSUFFICIENT", "Insufficient eligible observations for a usable diagnostic."
    robust = row["double_cost_net_return"] > 0 and row["delayed_execution_net_return"] > -0.05
    if (
        row["net_cumulative_return"] > 0
        and row["preliminary_oos_net_return"] >= -0.02
        and row["net_sharpe"] >= 0.35
        and robust
        and row["marginal_combined_portfolio_sharpe"] > 0
    ):
        return "ACTIVE", "Positive standalone, OOS, robustness, and marginal portfolio evidence."
    if row["net_cumulative_return"] <= 0 and row["preliminary_oos_net_return"] <= 0:
        return "ARCHIVED", "Full-period and preliminary OOS evidence are both clearly weak."
    return "REPAIR", "Potential value remains, but one or more robustness or admission gates failed."


def run_final_delivery_research(project_root: str | Path, *, user_agent: str) -> dict[str, object]:
    root = Path(project_root)
    output = root / OUTPUT_ROOT
    output.mkdir(parents=True, exist_ok=True)
    context = load_context(root / OHLCV_CACHE)
    facts = _load_facts(root, context, user_agent)
    raw = build_raw_component_panel(facts, context, context.panels["close"].index[::20])
    ensembles = _ensemble_scores(context)
    broad = ohlcv_candidate_scores(context)
    fundamental = fundamental_candidate_scores(raw, context.panels["close"].index, context.panels["close"].columns)
    event_scores = {
        "FILING_SHOCK_CONTINUATION": _rank_mean(
            raw, ["revenue_acceleration", "annual_ocf_growth", "annual_margin_change"]
        ).unstack("ticker").reindex(context.panels["close"].index).ffill(),
        "FUNDAMENTAL_SHOCK_RECOVERY": matched_control_recovery_score(raw, context)
        .unstack("ticker").reindex(context.panels["close"].index).ffill(),
    }
    scores = {"OVERNIGHT_INTRADAY_ENSEMBLE": ensembles["OVERNIGHT_INTRADAY_ENSEMBLE"]} | event_scores | broad | fundamental
    active = _active_returns(root / "dashboard/data/us_equity_research_bundle.json")
    active = active.drop(columns=[column for column in active.columns if column in CANDIDATE_SPECS], errors="ignore")
    active_base_sharpe = float(sharpe_ratio(active.mean(axis=1)))
    run_id = f"{PACK_ID}_{context.panels['close'].index.max().date().isoformat()}"
    summaries, daily_parts, holdings_parts, trade_parts, returns = [], [], [], [], {}

    for strategy_id in IMPLEMENTABLE_IDS:
        daily, holdings, trades, row = run_candidate(strategy_id, scores[strategy_id], context, run_id=run_id)
        candidate = daily.set_index("date")["net_return"]
        robustness = _robustness(scores[strategy_id], context)
        aligned = pd.concat([active, candidate.rename(strategy_id)], axis=1, join="inner")
        corr = aligned.corr().loc[strategy_id, active.columns].abs()
        row.update(
            robustness
            | {
                "actual_universe_used": "US_BROAD_LIQUID_POINT_IN_TIME_DIAGNOSTIC_FALLBACK",
                "maximum_active_correlation": float(corr.max()),
                "average_active_correlation": float(corr.mean()),
                "highest_active_correlation_strategy": str(corr.idxmax()),
                "marginal_combined_portfolio_sharpe": float(sharpe_ratio(aligned.mean(axis=1)) - active_base_sharpe),
                "economic_rationale": CANDIDATE_SPECS[strategy_id],
                "labels": "CURRENT_LISTED_DIAGNOSTIC | SURVIVORSHIP_BIAS_PRESENT | RESEARCH ONLY",
                "live_allocation_approved": False,
                "execution_enabled": False,
            }
        )
        status, reason = _classification(row)
        row["classification"], row["classification_reason"] = status, reason
        summaries.append(row)
        daily_parts.append(daily.assign(strategy_id=strategy_id))
        holdings_parts.append(holdings)
        trade_parts.append(trades)
        returns[strategy_id] = candidate

    summaries.append(
        {
            "strategy_id": "DELEVERAGING_PROFITABILITY",
            "classification": "DATA_INSUFFICIENT",
            "classification_reason": "SEC loader does not currently provide reliable point-in-time debt/assets or debt/equity history.",
            "actual_universe_used": "NONE",
            "labels": "CURRENT_LISTED_DIAGNOSTIC | SURVIVORSHIP_BIAS_PRESENT | RESEARCH ONLY",
            "live_allocation_approved": False,
            "execution_enabled": False,
            "economic_rationale": CANDIDATE_SPECS["DELEVERAGING_PROFITABILITY"],
        }
    )
    pd.concat(daily_parts, ignore_index=True).to_csv(output / "daily_strategy_returns.csv", index=False)
    pd.concat(holdings_parts, ignore_index=True).to_csv(output / "holdings.csv", index=False)
    pd.concat(trade_parts, ignore_index=True).to_csv(output / "trade_log.csv", index=False)
    return_panel = pd.DataFrame(returns)
    pd.concat([return_panel, active], axis=1, join="inner").corr().to_csv(output / "correlation_matrix.csv")
    regime_labels = _market_proxy_regime_labels(root, return_panel.index)
    regimes = []
    for strategy_id in return_panel:
        for regime in sorted(regime_labels.dropna().unique()):
            selected = return_panel.loc[regime_labels.eq(regime), strategy_id].dropna()
            regimes.append(
                {
                    "strategy_id": strategy_id, "regime_id": "MARKET_PROXY_REGIME_V0", "regime": regime,
                    "observations": len(selected), "net_cumulative_return": float(selected.add(1).prod() - 1),
                    "net_sharpe": float(sharpe_ratio(selected)), "alters_weights": False,
                }
            )
    regime_frame = pd.DataFrame(regimes)
    regime_frame.to_csv(output / "market_proxy_regime_v0.csv", index=False)
    for row in summaries:
        strategy_regimes = regime_frame.loc[regime_frame["strategy_id"].eq(row["strategy_id"])]
        if strategy_regimes.empty:
            row["regime_strength"] = "DATA_INSUFFICIENT"
            row["regime_weakness"] = "DATA_INSUFFICIENT"
        else:
            row["regime_strength"] = str(strategy_regimes.loc[strategy_regimes["net_sharpe"].idxmax(), "regime"])
            row["regime_weakness"] = str(strategy_regimes.loc[strategy_regimes["net_sharpe"].idxmin(), "regime"])
    pd.DataFrame(summaries).to_csv(output / "candidate_summary.csv", index=False)
    (output / "strategy_specification.json").write_text(json.dumps(CANDIDATE_SPECS, indent=2), encoding="utf-8")
    (output / "run_manifest.json").write_text(
        json.dumps(
            {
                "pack_id": PACK_ID, "status": "RESEARCH_ONLY", "execution": "NEXT_OPEN_TO_OPEN",
                "buy_bps": 5, "sell_bps": 5,
                "labels": ["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT", "RESEARCH ONLY"],
                "live_allocation_approved": False, "execution_enabled": False, "fill_status": "NO LIVE FILL",
                "market_proxy_regime": {"id": "MARKET_PROXY_REGIME_V0", "alters_weights": False},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"output_root": output, "summaries": summaries}
