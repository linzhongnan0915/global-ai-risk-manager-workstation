from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategies.expanded_selection_research import _sec_lookup, candidate_scores, classify
from src.strategies.fundamental_research import build_raw_component_panel
from tests.test_fundamental_research import _context, _facts


def test_sec_lookup_normalizes_dot_dash_variants():
    assert _sec_lookup({"BRK.B": "1"}, "BRK-B") == "1"
    assert _sec_lookup({"BF-B": "2"}, "BF.B") == "2"


def test_expanded_candidate_scores_preserve_missing_and_prior_information():
    context = _context(days=300, tickers=20)
    facts = _facts(context)
    raw = build_raw_component_panel(facts, context, context.panels["close"].index[::20])
    scores = candidate_scores(raw, context)
    assert len(scores) == 12
    changed = _context(days=300, tickers=20)
    changed.panels["adj_close"].iloc[-1] *= 10
    changed.panels["close"].iloc[-1] *= 10
    changed_scores = candidate_scores(raw, changed)
    pd.testing.assert_series_equal(
        scores["LOW_ACCRUAL_MOMENTUM"].iloc[-1], changed_scores["LOW_ACCRUAL_MOMENTUM"].iloc[-1]
    )
    missing = raw.loc[raw.index.get_level_values("ticker") != "T00"]
    missing_scores = candidate_scores(missing, context)
    assert np.isnan(missing_scores["GROSS_PROFITABILITY_GROWTH"]["T00"]).all()


def test_strict_gate_rejects_negative_or_low_sharpe():
    base = {
        "average_eligible_count": 30, "minimum_eligible_count": 25,
        "net_cumulative_return": 0.1, "preliminary_oos_net_return": 0.1, "net_sharpe": 0.3,
        "double_cost_net_return": 0.05, "delayed_execution_net_return": 0.05,
        "maximum_active_correlation": 0.5, "marginal_combined_portfolio_sharpe": 0.01,
        "eligible_portfolio_days": 20,
    }
    assert classify(base)[0] == "ACTIVE"
    assert classify(base | {"net_sharpe": 0.24})[0] == "REPAIR"
    assert classify(base | {"net_cumulative_return": -0.1, "preliminary_oos_net_return": -0.1})[0] == "ARCHIVED"
