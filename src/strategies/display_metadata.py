"""Canonical human-readable display metadata for operational strategies."""

from __future__ import annotations

from typing import Any

from src.strategies.c3a1_registry import C3A1_SPECS
from src.strategies.platform_registry import C3A2_SPECS
from src.strategies.wq_alpha018 import FORMULA as WQ_FORMULA
from src.strategies.wq_alpha018 import RESEARCH_SOURCE_COMMIT, WQ_ALPHA_018_SPEC


ACTIVE_DETAILS = {
    "COMBINED_PORTFOLIO": {
        "display_name": "Combined",
        "family": "Composite",
        "hypothesis_summary": "Diversify strategy-specific risk by equal-weighting every date-effective active underlying strategy.",
        "formula_module": "src.strategies.composite_membership",
        "signal_function": "composite_weights",
        "signal_summary": "Equal-weight composite of all date-effective active underlying strategies.",
        "universe": "Current date-effective active underlying strategies",
    },
    "FUNDAMENTAL_MOMENTUM": {
        "display_name": "Fundamental Momentum",
        "family": "Fundamental",
        "hypothesis_summary": "Prefer firms with improving revenue growth, operating margin, and operating cash flow relative to assets.",
        "formula_module": "src.strategies.fundamental_research",
        "signal_function": "build_candidate_scores[FUNDAMENTAL_MOMENTUM]",
        "signal_summary": "Cross-sectional rank mean of point-in-time revenue growth, margin change, and operating-cash-flow improvement.",
        "universe": "Point-in-time fundamental US equity universe",
    },
    "EARNINGS_QUALITY": {
        "display_name": "Earnings Quality",
        "family": "Fundamental",
        "hypothesis_summary": "Prefer cash-backed earnings with lower accruals and stronger operating cash conversion.",
        "formula_module": "src.strategies.fundamental_research",
        "signal_function": "build_candidate_scores[EARNINGS_QUALITY]",
        "signal_summary": "Ranks negative accruals, operating cash flow to revenue, and operating cash flow to net income.",
        "universe": "Point-in-time fundamental US equity universe",
    },
    "MARGIN_IMPROVEMENT": {
        "display_name": "Margin Improvement",
        "family": "Fundamental",
        "hypothesis_summary": "Prefer firms with improving operating and cash-flow margins.",
        "formula_module": "src.strategies.fundamental_research",
        "signal_function": "build_candidate_scores[MARGIN_IMPROVEMENT]",
        "signal_summary": "Cross-sectional rank of annual operating-margin and operating-cash-flow-margin changes.",
        "universe": "Point-in-time fundamental US equity universe",
    },
    "OVERNIGHT_INTRADAY_ENSEMBLE": {
        "display_name": "Overnight & Intraday Reversal Ensemble",
        "family": "Market Microstructure",
        "hypothesis_summary": "Combine overnight and prior-intraday reversal signals to capture short-horizon price normalization.",
        "formula_module": "src.strategies.diverse_strategy_research",
        "signal_function": "_ensemble_scores[OVERNIGHT_INTRADAY_ENSEMBLE]",
        "signal_summary": "Ensemble of lagged overnight and intraday reversal components.",
        "universe": "Broad liquid point-in-time US equity universe",
    },
    "FILING_SHOCK_CONTINUATION": {
        "display_name": "Filing Improvement Continuation",
        "family": "Event Driven",
        "hypothesis_summary": "Prefer continuation after point-in-time filing improvements in revenue, cash flow, and margins.",
        "formula_module": "src.strategies.frozen_active_signals",
        "signal_function": "frozen_active_scores filing_shock",
        "signal_summary": "Ranks filing-time revenue acceleration, annual cash-flow growth, and margin change.",
        "universe": "Point-in-time filing event universe",
    },
    "FUNDAMENTAL_SHOCK_RECOVERY": {
        "display_name": "Fundamental Shock Recovery",
        "family": "Event Driven",
        "hypothesis_summary": "Identify recovery following fundamental shocks using a matched-control diagnostic.",
        "formula_module": "src.strategies.diverse_strategy_research",
        "signal_function": "matched_control_recovery_score",
        "signal_summary": "Matched-control, causal-inspired recovery score from point-in-time fundamental events.",
        "universe": "Point-in-time filing event universe",
    },
    "CASH_FLOW_GROWTH_QUALITY": {
        "display_name": "Cash-Flow Growth Quality",
        "family": "Fundamental",
        "hypothesis_summary": "Prefer cash-flow growth supported by margin improvement and earnings quality.",
        "formula_module": "src.strategies.final_delivery_research",
        "signal_function": "fundamental_candidate_scores[CASH_FLOW_GROWTH_QUALITY]",
        "signal_summary": "Rank mean of cash-flow growth, cash-flow-margin improvement, and earnings quality.",
        "universe": "Point-in-time fundamental US equity universe",
    },
    "OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER": {
        "display_name": "Large-Gap Reversal, Reduced Turnover",
        "family": "Market Microstructure",
        "hypothesis_summary": "Fade only large overnight gaps while reducing rebalance frequency and transaction costs.",
        "formula_module": "src.strategies.expanded_selection_research",
        "signal_function": "candidate_scores[OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER]",
        "signal_summary": "Negative overnight gap signal activated only when the absolute gap exceeds two percent.",
        "universe": "OHLCV operational pricing universe",
    },
    "LIQUIDITY_ADJUSTED_MOMENTUM": {
        "display_name": "Liquidity-Adjusted Momentum",
        "family": "Momentum",
        "hypothesis_summary": "Prefer six-to-one-month momentum with stronger lagged dollar-volume support.",
        "formula_module": "src.strategies.ohlcv_alpha_expansion",
        "signal_function": "individual_scores[LIQUIDITY_ADJUSTED_MOMENTUM]",
        "signal_summary": "Weighted combination of six-to-one-month momentum and lagged dollar-volume rank.",
        "universe": "Expanded liquid point-in-time US equity universe",
    },
    "POST_FILING_CASH_FLOW_SURPRISE": {
        "display_name": "Post-Filing Cash-Flow Surprise",
        "family": "Event Driven",
        "hypothesis_summary": "Prefer post-publication continuation after unusually strong operating-cash-flow changes.",
        "formula_module": "src.strategies.event_panel_research",
        "signal_function": "event_scores[POST_FILING_CASH_FLOW_SURPRISE]",
        "signal_summary": "Positive operating-cash-flow change ranked within each filing date.",
        "universe": "Point-in-time filing event universe",
    },
    "WQ_ALPHA_018": {
        "display_name": "Low Intraday Range & Open-Close Correlation",
        "family": "Price Efficiency",
        "hypothesis_summary": "Prefer lower intraday range volatility and weaker close-open correlation.",
        "formula_module": "src.strategies.wq_alpha018",
        "signal_function": "wq_alpha_018_score",
        "signal_summary": WQ_FORMULA,
        "universe": "Current-listed diagnostic universe, survivorship bias present",
        "evidence_reference": RESEARCH_SOURCE_COMMIT,
    },
}


def strategy_display_metadata(strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build one stable mapping verified against registered specs and frozen dispatch."""
    specs = {spec.strategy_id: spec for spec in (*C3A1_SPECS, *C3A2_SPECS, WQ_ALPHA_018_SPEC)}
    result = []
    for row in strategies:
        internal_id = row["internal_id"]
        spec = specs.get(internal_id)
        detail = ACTIVE_DETAILS.get(internal_id, {})
        display_name = detail.get("display_name") or (spec.name if spec else row.get("name"))
        family = detail.get("family")
        if family is None:
            family = (
                "Momentum" if "Momentum" in display_name or "Strength" in display_name
                else "Liquidity" if "Illiquidity" in display_name
                else "Price Efficiency"
            )
        result.append(
            {
                "internal_id": internal_id,
                "display_id": row["display_id"],
                "display_name": display_name,
                "family": family,
                "hypothesis_summary": detail.get("hypothesis_summary") or (spec.hypothesis if spec else None),
                "signal_summary": detail.get("signal_summary") or (spec.hypothesis if spec else None),
                "formula_module": detail.get("formula_module") or (
                    "src.strategies.c3a1_registry" if internal_id.startswith("C3A1_")
                    else "src.strategies.platform_registry"
                ),
                "signal_function": detail.get("signal_function") or (
                    spec.signal_function.__name__ if spec else None
                ),
                "universe": detail.get("universe") or "Operational pricing universe",
                "rebalance_convention": "Every 20 observations, strategy-specific frozen rule",
                "execution_convention": "NEXT_OPEN_TO_OPEN record; execution provenance status controls verification label; No Live Brokerage Fill",
                "evidence_reference": detail.get("evidence_reference"),
                "status": row["membership_state"],
                "effective_date": row.get("effective_from"),
            }
        )
    return result
