"""Deployment checks for retained strategies and Strategy 21 registry."""

from pathlib import Path

import pandas as pd

from src.strategies.liquidity_resilience import liquidity_resilience_score
from src.strategies.realized_skewness import realized_skewness_score
from src.strategies.shadow_mvp import COMPOSITE_ID, platform_strategy_registry
from src.strategies.strategy_factory import StrategyContext


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_registry_has_only_retained_research_strategies():
    rows = platform_strategy_registry(Path("unused"), Path("unused"), "ALL")
    assert {row["strategy_id"] for row in rows} == {"C2A2_020", "C2B2_004", COMPOSITE_ID}
    assert next(row for row in rows if row["strategy_id"] == COMPOSITE_ID)["status"] == "RESEARCH_COMPOSITE"
    assert all(not row["allocation_eligible"] for row in rows)
    assert all(row["strategy_21_allocation"] == 0 for row in rows if row["status"] in {"ARCHIVE", "BLOCKED"})


def test_retained_signals_use_shared_strategy_context():
    dates = pd.bdate_range("2026-01-01", periods=80)
    prices = pd.DataFrame({"A": range(100, 180), "B": range(180, 100, -1)}, index=dates, dtype=float)
    returns = prices.pct_change(fill_method=None)
    context = StrategyContext(
        panels={"close": prices, "volume": prices * 1000},
        daily_returns=returns,
        market_return=returns.mean(axis=1),
        lagged_beta=prices * 0 + 1,
        lagged_adv=prices * 0 + 10_000_000,
    )
    assert liquidity_resilience_score(context).shape == prices.shape
    assert realized_skewness_score(context).shape == prices.shape
