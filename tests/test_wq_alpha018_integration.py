from pathlib import Path
import json

import numpy as np
import pandas as pd

from src.strategies.shadow_live_membership import (
    CURRENT_ACTIVE_IDS,
    LEGACY_ACTIVE_IDS,
    WQ_ALPHA_018_EFFECTIVE_DATE,
    active_ids_for,
    equal_weight_for,
)
from src.strategies.platform_registry import WORLDQUANT_ALPHA_SELECTION_STATUS
from src.strategies.worldquant.operators import correlation_ts, rank_cs
from src.strategies.wq_alpha018 import FORMULA, RESEARCH_METRICS, wq_alpha_018_score
from tests.test_fundamental_research import _context


def test_locked_formula_and_prior_information_only():
    context = _context(days=320, tickers=120)
    actual = wq_alpha_018_score(context)
    open_ = context.panels["open"].shift(1)
    close = context.panels["close"].shift(1)
    spread = close - open_
    expected = -rank_cs(
        spread.abs().rolling(5, min_periods=5).std()
        + spread
        + correlation_ts(close, open_, 10)
    )
    pd.testing.assert_frame_equal(actual, expected)

    changed = _context(days=320, tickers=120)
    changed.panels["open"].iloc[-1] *= 10
    changed.panels["close"].iloc[-1] *= 10
    pd.testing.assert_series_equal(actual.iloc[-1], wq_alpha_018_score(changed).iloc[-1])
    assert FORMULA == "-rank(stddev(abs(close-open),5)+(close-open)+correlation(close,open,10))"


def test_locked_research_evidence_and_date_effective_membership():
    assert RESEARCH_METRICS["net_sharpe"] == 0.523461244769271
    assert RESEARCH_METRICS["preliminary_oos_net_return"] > 0
    assert RESEARCH_METRICS["double_cost_net_return"] > 0
    assert RESEARCH_METRICS["delayed_execution_net_return"] > 0
    assert RESEARCH_METRICS["maximum_active_correlation"] < 0.14
    assert RESEARCH_METRICS["marginal_combined_portfolio_sharpe"] > 0
    assert len(LEGACY_ACTIVE_IDS) == 16
    assert len(CURRENT_ACTIVE_IDS) == 17
    assert active_ids_for("2026-06-12") == LEGACY_ACTIVE_IDS
    assert active_ids_for(WQ_ALPHA_018_EFFECTIVE_DATE) == CURRENT_ACTIVE_IDS
    assert np.isclose(equal_weight_for("2026-06-12"), 1 / 16)
    assert np.isclose(equal_weight_for(WQ_ALPHA_018_EFFECTIVE_DATE), 1 / 17)
    assert WORLDQUANT_ALPHA_SELECTION_STATUS["WQ_ALPHA_018"]["status"] == "ACTIVE"


def test_committed_membership_log_and_pending_target_contract():
    payload = json.loads(Path("dashboard/data/shadow_live_bundle.json").read_text(encoding="utf-8"))
    shadow = payload["shadow_live"]
    row = shadow["membership_timeline"][-1]
    pending = [target for target in shadow["pending_targets"] if target["strategy_id"] == "WQ_ALPHA_018"]
    assert row["effective_date"] == WQ_ALPHA_018_EFFECTIVE_DATE
    assert row["previous_active_count"] == 16
    assert row["new_active_count"] == 17
    assert np.isclose(row["new_equal_weight"], 1 / 17)
    assert row["live_allocation_approved"] is False
    assert row["integration_commit"] == "6832fbe5854d5c0b6b3a47a04855f54858983db7"
    assert pending
    assert all(target["data_status"] == "PENDING_EXECUTION" for target in pending)
    assert all(target["signal_date"] == "2026-06-12" for target in pending)


def test_research_bundle_ports_only_validated_strategy_and_prospective_membership():
    payload = json.loads(Path("dashboard/data/us_equity_research_bundle.json").read_text(encoding="utf-8"))
    catalog = payload["factory_strategy_research"]
    wq = [row for row in catalog["results"] if row["strategy_id"] == "WQ_ALPHA_018"]
    assert len(wq) == 1
    assert wq[0]["backtest"]["factory_research"]["membership"] == "ACTIVE"
    assert wq[0]["backtest"]["factory_research"]["live_allocation_approved"] is False
    composite = next(row for row in catalog["results"] if row["strategy_id"] == "COMBINED_PORTFOLIO_V1")
    membership = composite["backtest"]["factory_research"]["combined_portfolio"]
    assert membership["N"] == 17
    assert np.isclose(sum(membership["weights"].values()), 1.0)
    assert membership["membership_effective_date"] == WQ_ALPHA_018_EFFECTIVE_DATE
    assert membership["prospective_only"] is True
