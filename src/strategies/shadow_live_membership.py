"""Date-effective, append-only shadow-live strategy membership."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

LEGACY_ACTIVE_IDS = (
    "C3A1_002", "C3A1_003", "C3A1_013", "C3A2_008", "C3A1_001", "C3A1_015",
    "FUNDAMENTAL_MOMENTUM", "EARNINGS_QUALITY", "MARGIN_IMPROVEMENT",
    "OVERNIGHT_INTRADAY_ENSEMBLE", "FILING_SHOCK_CONTINUATION",
    "FUNDAMENTAL_SHOCK_RECOVERY", "CASH_FLOW_GROWTH_QUALITY",
    "OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER", "LIQUIDITY_ADJUSTED_MOMENTUM",
    "POST_FILING_CASH_FLOW_SURPRISE",
)
CURRENT_ACTIVE_IDS = LEGACY_ACTIVE_IDS + ("WQ_ALPHA_018",)
WQ_ALPHA_018_EFFECTIVE_DATE = "2026-06-15"
MEMBERSHIP_LOG = Path("output/shadow_live/composite_membership_log.csv")


def active_ids_for(execution_date: str | date | pd.Timestamp) -> tuple[str, ...]:
    value = pd.Timestamp(execution_date).date()
    return CURRENT_ACTIVE_IDS if value >= pd.Timestamp(WQ_ALPHA_018_EFFECTIVE_DATE).date() else LEGACY_ACTIVE_IDS


def active_count_for(execution_date: str | date | pd.Timestamp) -> int:
    return len(active_ids_for(execution_date))


def equal_weight_for(execution_date: str | date | pd.Timestamp) -> float:
    return 1.0 / active_count_for(execution_date)
