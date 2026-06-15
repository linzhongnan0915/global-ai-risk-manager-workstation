from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategies.diverse_strategy_research import combine_components, normalize_component
from src.strategies.fundamental_research import build_trade_log


def test_signal_components_are_normalized_and_combined_before_returns():
    dates = pd.bdate_range("2024-01-02", periods=2)
    first = pd.DataFrame({"A": [1, 3], "B": [2, 2], "C": [3, 1]}, index=dates)
    second = -first
    combined = combine_components([first, second], [0.5, 0.5])
    assert np.allclose(combined.fillna(0), 0)
    assert normalize_component(first).max().max() <= 1
    assert normalize_component(first).min().min() >= -1


def test_opposing_target_changes_net_before_trade_costs():
    dates = pd.bdate_range("2024-01-02", periods=2)
    target = pd.DataFrame({"A": [0.5, 0.0], "B": [-0.5, 0.0]}, index=dates)
    prices = pd.DataFrame(10.0, index=dates, columns=["A", "B"])
    trades = build_trade_log("ENSEMBLE", target, prices, run_id="TEST")
    assert trades["turnover_contribution"].sum() == pytest.approx(1.0)
    assert trades["estimated_transaction_cost"].sum() == pytest.approx(0.0005)
