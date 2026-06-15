"""Final OHLCV alpha expansion on the expanded liquid diagnostic universe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.risk.performance import sharpe_ratio
from src.strategies.diverse_strategy_research import _active_returns, _market_proxy_regime_labels, combine_components
from src.strategies.expanded_selection_research import MIN_CROSS_SECTION, OHLCV_CACHE, _mask, classify
from src.strategies.final_delivery_research import _robustness
from src.strategies.fundamental_research import run_candidate
from src.strategies.strategy_factory import StrategyContext, load_context
from src.strategies.universe_foundation import diagnostic_broad_membership

PACK_ID = "FINAL_OHLCV_ALPHA_EXPANSION_V1"
OUTPUT_ROOT = Path("output/research/final_ohlcv_alpha_expansion_v1")

INDIVIDUAL_IDS = (
    "RESIDUAL_SHORT_TERM_REVERSAL",
    "VOLUME_PRICE_DIVERGENCE_REVERSAL",
    "RANGE_COMPRESSION_BREAKOUT",
    "LOW_BETA_DEFENSIVE",
    "IDIOSYNCRATIC_VOLATILITY_REVERSAL",
    "LIQUIDITY_ADJUSTED_MOMENTUM",
    "GAP_VOLUME_CONTINUATION",
    "DRAWDOWN_RECOVERY",
    "INTRADAY_STRENGTH_PERSISTENCE",
    "DISPERSION_CONDITIONAL_MOMENTUM",
)

RATIONALES = {
    "RESIDUAL_SHORT_TERM_REVERSAL": "Fade five-day returns after removing the lagged broad-market component.",
    "VOLUME_PRICE_DIVERGENCE_REVERSAL": "Fade short-term price moves when recent volume diverges above its trailing baseline.",
    "RANGE_COMPRESSION_BREAKOUT": "Prefer directional breakouts following unusually compressed prior trading ranges.",
    "LOW_BETA_DEFENSIVE": "Prefer lower lagged broad-market beta.",
    "IDIOSYNCRATIC_VOLATILITY_REVERSAL": "Fade short-term residual moves scaled by lagged idiosyncratic volatility.",
    "LIQUIDITY_ADJUSTED_MOMENTUM": "Prefer six-to-one-month momentum with stronger lagged dollar-volume support.",
    "GAP_VOLUME_CONTINUATION": "Follow prior overnight gaps confirmed by abnormal volume.",
    "DRAWDOWN_RECOVERY": "Prefer positive short-term recovery while still below the prior rolling high.",
    "INTRADAY_STRENGTH_PERSISTENCE": "Prefer persistent prior open-to-close strength.",
    "DISPERSION_CONDITIONAL_MOMENTUM": "Apply medium-term momentum only when cross-sectional return dispersion is elevated.",
}


def _lagged_beta(context: StrategyContext, window: int = 126) -> pd.DataFrame:
    market = context.market_return
    variance = market.rolling(window, min_periods=window).var().shift(1)
    return context.daily_returns.rolling(window, min_periods=window).cov(market).div(variance, axis=0).shift(1)


def individual_scores(context: StrategyContext) -> dict[str, pd.DataFrame]:
    """Frozen v1 formulas; every component uses information available before the signal close."""
    returns = context.daily_returns
    close = context.panels["adj_close"]
    volume = context.panels["volume"]
    beta = _lagged_beta(context)
    residual = returns.sub(beta.mul(context.market_return, axis=0))
    residual_5d = residual.rolling(5, min_periods=5).sum().shift(1)
    residual_vol = residual.rolling(63, min_periods=63).std().shift(1).replace(0, np.nan)
    return_5d = close.shift(1).div(close.shift(6)).sub(1)
    return_20d = close.shift(1).div(close.shift(21)).sub(1)
    volume_ratio = volume.shift(1).rolling(5, min_periods=5).mean().div(
        volume.shift(6).rolling(63, min_periods=63).mean().replace(0, np.nan)
    )
    range_pct = context.panels["high"].sub(context.panels["low"]).div(context.panels["close"].replace(0, np.nan))
    range_compression = -range_pct.shift(1).rolling(20, min_periods=20).mean().div(
        range_pct.shift(21).rolling(126, min_periods=126).mean().replace(0, np.nan)
    )
    momentum_6_1 = close.shift(21).div(close.shift(126)).sub(1)
    adv_rank = context.lagged_adv.rank(axis=1, pct=True)
    prior_gap = context.panels["open"].shift(1).div(context.panels["close"].shift(2)).sub(1)
    volume_z = volume.shift(1).sub(volume.shift(1).rolling(63, min_periods=63).mean()).div(
        volume.shift(1).rolling(63, min_periods=63).std().replace(0, np.nan)
    )
    prior_high = close.shift(1).rolling(126, min_periods=126).max()
    drawdown = close.shift(1).div(prior_high).sub(1)
    prior_intraday = context.panels["close"].div(context.panels["open"]).sub(1).shift(1)
    dispersion = return_20d.std(axis=1)
    high_dispersion = dispersion.gt(dispersion.rolling(252, min_periods=126).median())

    return {
        "RESIDUAL_SHORT_TERM_REVERSAL": -residual_5d,
        "VOLUME_PRICE_DIVERGENCE_REVERSAL": -return_5d.mul(volume_ratio.clip(lower=1)),
        "RANGE_COMPRESSION_BREAKOUT": combine_components([return_20d, range_compression], [0.65, 0.35]),
        "LOW_BETA_DEFENSIVE": -beta,
        "IDIOSYNCRATIC_VOLATILITY_REVERSAL": -residual_5d.div(residual_vol),
        "LIQUIDITY_ADJUSTED_MOMENTUM": combine_components([momentum_6_1, adv_rank], [0.75, 0.25]),
        "GAP_VOLUME_CONTINUATION": prior_gap.mul(volume_z.clip(lower=0)),
        "DRAWDOWN_RECOVERY": return_20d.mul((-drawdown).clip(lower=0)),
        "INTRADAY_STRENGTH_PERSISTENCE": prior_intraday.rolling(5, min_periods=5).sum(),
        "DISPERSION_CONDITIONAL_MOMENTUM": momentum_6_1.where(high_dispersion, np.nan),
    }


def _evaluate(
    strategy_id: str, score: pd.DataFrame, context: StrategyContext, active: pd.DataFrame,
    active_base_sharpe: float, *, run_id: str, rationale: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    daily, holdings, trades, row = run_candidate(strategy_id, score, context, run_id=run_id)
    candidate = daily.set_index("date")["net_return"]
    aligned = pd.concat([active, candidate.rename(strategy_id)], axis=1, join="inner")
    correlations = aligned.corr().loc[strategy_id, active.columns].abs()
    row.update(_robustness(score, context))
    row.update({
        "maximum_active_correlation": float(correlations.max()),
        "average_active_correlation": float(correlations.mean()),
        "highest_active_correlation_strategy": str(correlations.idxmax()),
        "marginal_combined_portfolio_sharpe": float(sharpe_ratio(aligned.mean(axis=1)) - active_base_sharpe),
        "actual_universe_used": "OHLCV_UNIVERSE",
        "economic_rationale": rationale,
        "labels": "CURRENT_LISTED_DIAGNOSTIC | SURVIVORSHIP_BIAS_PRESENT | RESEARCH ONLY",
        "live_allocation_approved": False, "execution_enabled": False,
    })
    eligible_counts = score.notna().sum(axis=1)
    row["eligible_portfolio_days"] = int(eligible_counts.ge(MIN_CROSS_SECTION).sum())
    row["minimum_eligible_count"] = int(eligible_counts.loc[eligible_counts.ge(MIN_CROSS_SECTION)].min()) if row["eligible_portfolio_days"] else 0
    row["classification"], row["classification_reason"] = classify(row)
    return daily, holdings, trades, row


def run_ohlcv_alpha_expansion(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    output = root / OUTPUT_ROOT
    output.mkdir(parents=True, exist_ok=True)
    context = load_context(root / OHLCV_CACHE)
    signal_dates = context.panels["close"].index[::20]
    broad = diagnostic_broad_membership(signal_dates, context.panels["close"], context.lagged_adv)
    broad_mask = _mask(broad, context.panels["close"].index, context.panels["close"].columns)
    scores = {key: value.where(broad_mask) for key, value in individual_scores(context).items()}
    active = _active_returns(root / "dashboard/data/us_equity_research_bundle.json")
    active_base_sharpe = float(sharpe_ratio(active.mean(axis=1)))
    run_id = f"{PACK_ID}_{context.panels['close'].index.max().date().isoformat()}"
    summaries, daily_parts, holdings_parts, trade_parts, returns = [], [], [], [], {}
    for strategy_id, score in scores.items():
        daily, holdings, trades, row = _evaluate(
            strategy_id, score, context, active, active_base_sharpe, run_id=run_id, rationale=RATIONALES[strategy_id]
        )
        summaries.append(row)
        daily_parts.append(daily.assign(strategy_id=strategy_id))
        holdings_parts.append(holdings)
        trade_parts.append(trades)
        returns[strategy_id] = daily.set_index("date")["net_return"]

    pd.DataFrame(summaries).to_csv(output / "candidate_summary.csv", index=False)
    pd.concat(daily_parts, ignore_index=True).to_csv(output / "daily_strategy_returns.csv", index=False)
    pd.concat(holdings_parts, ignore_index=True).to_csv(output / "holdings.csv", index=False)
    pd.concat(trade_parts, ignore_index=True).to_csv(output / "trade_log.csv", index=False)
    return_panel = pd.DataFrame(returns)
    pd.concat([return_panel, active], axis=1, join="inner").corr().to_csv(output / "correlation_matrix.csv")
    regime_labels = _market_proxy_regime_labels(root, return_panel.index)
    regime_rows = []
    for strategy_id in return_panel:
        for regime in sorted(regime_labels.dropna().unique()):
            selected = return_panel.loc[regime_labels.eq(regime), strategy_id].dropna()
            regime_rows.append({
                "strategy_id": strategy_id, "regime_id": "MARKET_PROXY_REGIME_V0", "regime": regime,
                "observations": len(selected), "net_cumulative_return": float(selected.add(1).prod() - 1),
                "net_sharpe": float(sharpe_ratio(selected)) if len(selected) > 1 else np.nan, "alters_weights": False,
            })
    pd.DataFrame(regime_rows).to_csv(output / "market_proxy_regime_v0.csv", index=False)
    (output / "strategy_specification.json").write_text(json.dumps(RATIONALES, indent=2), encoding="utf-8")
    (output / "run_manifest.json").write_text(json.dumps({
        "pack_id": PACK_ID, "status": "RESEARCH_ONLY", "execution": "NEXT_OPEN_TO_OPEN",
        "buy_bps": 5, "sell_bps": 5, "universe": "expanded 229-name latest-liquid diagnostic universe",
        "labels": ["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT", "RESEARCH ONLY"],
        "ensemble_result": "No ensemble created because fewer than two complementary individual signals passed all gates.",
        "live_allocation_approved": False, "execution_enabled": False, "fill_status": "NO LIVE FILL",
    }, indent=2), encoding="utf-8")
    return {"output_root": output, "summaries": summaries}
