"""Focused tests for the next_open_to_open research execution convention."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategies.strategy_factory import StrategySpec, rank_and_weight, common_eligibility
from src.strategies.worldquant.portfolio_returns import (
    EXECUTION_MODE_NEXT_OPEN_TO_OPEN,
    build_asset_return_panel,
    compute_portfolio_returns_from_weights,
    resolve_execution_spec,
)


def test_next_open_to_open_return_uses_open_t_to_open_t_plus_one():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    open_prices = pd.DataFrame(
        {"A": [100.0, 102.0, 104.0]},
        index=dates,
    )
    close = open_prices + 1.0
    returns = build_asset_return_panel(open_prices, close, close, execution_mode=EXECUTION_MODE_NEXT_OPEN_TO_OPEN)
    assert np.isclose(returns.loc[dates[0], "A"], 0.02)
    assert np.isclose(returns.loc[dates[1], "A"], 104.0 / 102.0 - 1.0)
    assert pd.isna(returns.loc[dates[2], "A"])


def test_two_day_synthetic_example_includes_overnight_move():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    open_prices = pd.DataFrame({"A": [100.0, 103.0]}, index=dates)
    close = pd.DataFrame({"A": [101.0, 104.0]}, index=dates)
    open_to_close = close / open_prices - 1.0
    open_to_open = build_asset_return_panel(open_prices, close, close, execution_mode=EXECUTION_MODE_NEXT_OPEN_TO_OPEN)
    assert open_to_open.loc[dates[0], "A"] > open_to_close.loc[dates[0], "A"]


def test_final_unavailable_return_is_not_zero_filled():
    dates = pd.bdate_range("2024-01-02", periods=3)
    weights = pd.DataFrame({"A": [1.0, 1.0, 1.0]}, index=dates)
    returns = build_asset_return_panel(
        pd.DataFrame({"A": [100.0, 101.0, 102.0]}, index=dates),
        pd.DataFrame({"A": [100.5, 101.5, 102.5]}, index=dates),
        pd.DataFrame({"A": [100.0, 101.0, 102.0]}, index=dates),
        execution_mode=EXECUTION_MODE_NEXT_OPEN_TO_OPEN,
    )
    result = compute_portfolio_returns_from_weights(
        weights, returns, execution_lag=0, buy_bps=5, sell_bps=5, return_definition="open_to_open"
    )
    assert pd.isna(result.gross_return.iloc[-1])
    assert pd.isna(result.net_return.iloc[-1])


def test_unchanged_weights_have_zero_turnover_and_cost():
    dates = pd.bdate_range("2024-01-02", periods=3)
    weights = pd.DataFrame({"A": [0.5, 0.5, 0.5], "B": [-0.5, -0.5, -0.5]}, index=dates)
    returns = pd.DataFrame({"A": [0.01, 0.01, np.nan], "B": [-0.01, -0.01, np.nan]}, index=dates)
    result = compute_portfolio_returns_from_weights(
        weights, returns, execution_lag=0, buy_bps=5, sell_bps=5, return_definition="open_to_open"
    )
    assert result.turnover.iloc[1] == 0.0
    assert result.transaction_cost.iloc[1] == 0.0


def test_rebalance_weight_change_generates_cost():
    dates = pd.bdate_range("2024-01-02", periods=3)
    weights = pd.DataFrame({"A": [0.5, 0.0, 0.0], "B": [-0.5, 0.0, 0.0]}, index=dates)
    returns = pd.DataFrame({"A": [0.01, 0.01, np.nan], "B": [-0.01, -0.01, np.nan]}, index=dates)
    result = compute_portfolio_returns_from_weights(
        weights, returns, execution_lag=0, buy_bps=10, sell_bps=10, return_definition="open_to_open"
    )
    assert result.turnover.iloc[1] > 0
    assert result.transaction_cost.iloc[1] > 0


def test_signal_ranking_uses_prior_day_information_only():
    dates = pd.bdate_range("2024-01-02", periods=5)
    close = pd.DataFrame({"A": [10, 11, 12, 13, 99], "B": [10, 9, 8, 7, 1]}, index=dates)
    context_panels = {
        "close": close,
        "adj_close": close.copy(),
        "open": close.copy(),
        "high": close * 1.01,
        "low": close * 0.99,
        "volume": close * 0 + 1_000_000,
    }
    from src.strategies.strategy_factory import StrategyContext

    context = StrategyContext(
        context_panels,
        close.pct_change(fill_method=None),
        close.pct_change(fill_method=None).mean(axis=1),
        close * 0 + 1.0,
        close * 0 + 20_000_000,
    )
    score = close.shift(1)
    spec = StrategySpec("TEST", "v1", "test", "test", lambda c: c.panels["close"], 1, min_cross_section=2)
    eligible = common_eligibility(score, context, spec)
    weights, _ = rank_and_weight(score, eligible, spec)
    assert weights.loc[dates[-1], "A"] == weights.loc[dates[-2], "A"]
