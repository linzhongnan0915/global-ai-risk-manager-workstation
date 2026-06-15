"""Frozen dispatch for accepted ACTIVE strategy signal functions."""

from __future__ import annotations

import pandas as pd

from src.strategies.c3a1_registry import C3A1_SPECS
from src.strategies.diverse_strategy_research import _ensemble_scores, matched_control_recovery_score
from src.strategies.event_panel_research import event_scores
from src.strategies.expanded_selection_research import candidate_scores as expanded_candidate_scores
from src.strategies.final_delivery_research import fundamental_candidate_scores
from src.strategies.fundamental_data import build_filing_event_panel
from src.strategies.fundamental_research import build_candidate_scores, build_raw_component_panel
from src.strategies.ohlcv_alpha_expansion import individual_scores
from src.strategies.platform_registry import C3A2_SPECS
from src.strategies.strategy_factory import StrategyContext, StrategySpec
from src.strategies.shadow_live_membership import CURRENT_ACTIVE_IDS
from src.strategies.wq_alpha018 import WQ_ALPHA_018_SPEC, wq_alpha_018_score

ACTIVE_IDS = CURRENT_ACTIVE_IDS


def frozen_active_scores(
    context: StrategyContext,
    facts: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], dict[str, StrategySpec]]:
    """Invoke each existing frozen signal formula on raw point-in-time inputs."""
    dates, tickers = context.panels["close"].index, context.panels["close"].columns
    specs = {spec.strategy_id: spec for spec in (*C3A1_SPECS, *C3A2_SPECS) if spec.strategy_id in ACTIVE_IDS}
    scores = {strategy_id: spec.signal_function(context) for strategy_id, spec in specs.items()}

    signal_dates = dates[::20]
    raw = build_raw_component_panel(facts, context, signal_dates)
    fundamental = build_candidate_scores(raw, dates, tickers)
    delivery_fundamental = fundamental_candidate_scores(raw, dates, tickers)
    expanded = expanded_candidate_scores(raw, context)
    events = build_filing_event_panel(facts, dates)
    event = event_scores(events, context)
    filing_shock = (
        raw[["revenue_acceleration", "annual_ocf_growth", "annual_margin_change"]]
        .groupby(level="date").rank(pct=True).mean(axis=1)
        .unstack("ticker").reindex(index=dates, columns=tickers).ffill()
    )
    recovery = matched_control_recovery_score(raw, context).unstack("ticker").reindex(index=dates, columns=tickers).ffill()

    scores.update({
        "FUNDAMENTAL_MOMENTUM": fundamental["FUNDAMENTAL_MOMENTUM"],
        "EARNINGS_QUALITY": fundamental["EARNINGS_QUALITY"],
        "MARGIN_IMPROVEMENT": fundamental["MARGIN_IMPROVEMENT"],
        "OVERNIGHT_INTRADAY_ENSEMBLE": _ensemble_scores(context)["OVERNIGHT_INTRADAY_ENSEMBLE"],
        "FILING_SHOCK_CONTINUATION": filing_shock,
        "FUNDAMENTAL_SHOCK_RECOVERY": recovery,
        "CASH_FLOW_GROWTH_QUALITY": delivery_fundamental["CASH_FLOW_GROWTH_QUALITY"],
        "OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER": expanded["OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER"],
        "LIQUIDITY_ADJUSTED_MOMENTUM": individual_scores(context)["LIQUIDITY_ADJUSTED_MOMENTUM"],
        "POST_FILING_CASH_FLOW_SURPRISE": event["POST_FILING_CASH_FLOW_SURPRISE"],
        "WQ_ALPHA_018": wq_alpha_018_score(context),
    })
    specs["WQ_ALPHA_018"] = WQ_ALPHA_018_SPEC
    for strategy_id in ACTIVE_IDS:
        if strategy_id not in specs:
            specs[strategy_id] = StrategySpec(
                strategy_id, f"{strategy_id.lower()}_frozen_v1", strategy_id.replace("_", " ").title(),
                "Frozen accepted strategy formula.", lambda _context, value=scores[strategy_id]: value,
                20, min_cross_section=20,
            )
    return scores, specs
