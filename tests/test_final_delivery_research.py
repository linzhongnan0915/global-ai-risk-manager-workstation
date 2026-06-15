from __future__ import annotations

import numpy as np
import pandas as pd
import json
from pathlib import Path
import pytest

from src.strategies.final_delivery_research import fundamental_candidate_scores, ohlcv_candidate_scores
from src.strategies.fundamental_research import build_raw_component_panel
from tests.test_fundamental_research import _context, _facts

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/research/final_platform_delivery_v1"
BUNDLE = ROOT / "dashboard/data/us_equity_research_bundle.json"


def test_new_ohlcv_formulas_use_prior_information_and_preserve_shape():
    context = _context(days=300, tickers=20)
    scores = ohlcv_candidate_scores(context)
    assert len(scores) == 4
    assert all(score.shape == context.panels["close"].shape for score in scores.values())
    changed = _context(days=300, tickers=20)
    changed.panels["close"].iloc[-1] *= 10
    changed.panels["adj_close"].iloc[-1] *= 10
    changed_scores = ohlcv_candidate_scores(changed)
    for strategy_id in scores:
        pd.testing.assert_series_equal(scores[strategy_id].iloc[-1], changed_scores[strategy_id].iloc[-1])


def test_new_fundamental_scores_preserve_missing_quality():
    context = _context(days=80, tickers=20)
    facts = _facts(context)
    facts = facts.loc[
        ~(
            (facts["ticker"] == "T00")
            & facts["field"].isin(["gross_profit", "operating_income", "operating_cash_flow"])
        )
    ]
    raw = build_raw_component_panel(facts, context, context.panels["close"].index)
    scores = fundamental_candidate_scores(raw, context.panels["close"].index, context.panels["close"].columns)
    assert len(scores) == 3
    assert np.isnan(scores["REVENUE_ACCELERATION_QUALITY"].loc[pd.Timestamp("2024-02-16"), "T00"])


def test_final_delivery_outputs_and_bundle_reconcile():
    summary = pd.read_csv(OUTPUT / "candidate_summary.csv")
    daily = pd.read_csv(OUTPUT / "daily_strategy_returns.csv")
    trades = pd.read_csv(OUTPUT / "trade_log.csv")
    assert summary["classification"].value_counts().to_dict() == {
        "ACTIVE": 4, "DATA_INSUFFICIENT": 3, "REPAIR": 2, "ARCHIVED": 2
    }
    for strategy_id in daily["strategy_id"].unique():
        daily_cost = daily.loc[daily["strategy_id"].eq(strategy_id), "transaction_cost"].sum()
        trade_cost = trades.loc[trades["strategy_id"].eq(strategy_id), "estimated_transaction_cost"].sum()
        assert trade_cost == pytest.approx(daily_cost)
    payload = json.loads(BUNDLE.read_text(encoding="utf-8"))["factory_strategy_research"]
    rows = {row["strategy_id"]: row for row in payload["results"]}
    composite = rows["COMBINED_PORTFOLIO_V1"]["backtest"]["factory_research"]["combined_portfolio"]
    assert composite["N"] == 16
    assert sum(composite["weights"].values()) == pytest.approx(1.0)
    assert all(weight == pytest.approx(1 / 16) for weight in composite["weights"].values())
    for strategy_id in summary["strategy_id"]:
        backtest = rows[strategy_id]["backtest"]
        assert backtest["live_allocation_approved"] is False
        assert backtest["execution_enabled"] is False
        assert "NO LIVE FILL" in backtest["factory_research"]["simulated_trade_log"]["status"]
        assert backtest["factory_research"]["data_labels"] == [
            "CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT", "RESEARCH ONLY"
        ]
