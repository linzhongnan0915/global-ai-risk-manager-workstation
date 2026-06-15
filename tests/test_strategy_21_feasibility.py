"""Focused checks for minimal Strategy 21 feasibility analysis."""

import numpy as np
import pandas as pd

from src.strategies.strategy_21_feasibility import build_composite, candidate_decisions, pairwise_analysis


def test_pairwise_analysis_uses_aligned_dates_and_correlation():
    index = pd.date_range("2025-01-01", periods=70)
    returns = pd.DataFrame({"A": np.arange(70), "B": np.arange(70) * 2, "C": -np.arange(70)}, index=index)
    audit = pd.DataFrame({"date": [index[0]], "ticker": ["X"], "target_weight": [0.5]})
    result = pairwise_analysis(returns, {"A": audit, "B": audit, "C": audit})
    assert result.loc[(result["strategy_left"] == "A") & (result["strategy_right"] == "B"), "daily_net_return_correlation"].iloc[0] == 1.0


def test_equal_weight_composite_zeroes_nonretained_and_reconciles_contributions():
    index = pd.date_range("2025-01-01", periods=3)
    returns = pd.DataFrame({"A": [0.01, 0.02, 0.03], "B": [0.03, 0.02, 0.01], "ARCHIVED": [1, 1, 1]}, index=index)
    daily, summary = build_composite(returns, ["A", "B"])
    assert summary["weights"] == {"A": 0.5, "B": 0.5, "ARCHIVED": 0.0}
    assert np.allclose(daily["net_return"], [0.02, 0.02, 0.02])
    assert summary["component_contribution"]["ARCHIVED"] == 0.0
    assert summary["contribution_reconciliation_error"] < 1e-12


def test_duplicate_pair_retains_stronger_representative():
    pairwise = pd.DataFrame(
        [{"strategy_left": "C2A2_002", "strategy_right": "C2A2_020", "distinctness_decision": "ECONOMICALLY_DUPLICATE"}]
    )
    summaries = {
        "C2A2_002": {"net_sharpe": 0.6}, "C2A2_020": {"net_sharpe": 0.7}, "C2B2_004": {"net_sharpe": 0.5}
    }
    decisions = candidate_decisions(pairwise, summaries)
    assert decisions["C2A2_002"] == "REMOVE_FROM_COMPOSITE"
    assert decisions["C2A2_020"] == "RETAIN_BUT_OVERLAPPING"
