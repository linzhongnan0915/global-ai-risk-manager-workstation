from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.strategies.platform_registry import (
    CHALLENGE_SELECTION_STATUS,
    EVENT_PANEL_CANDIDATE_IDS,
    EVENT_PANEL_SELECTION_STATUS,
    FUNDAMENTAL_RESEARCH_CANDIDATE_IDS,
    FUNDAMENTAL_SELECTION_STATUS,
    FINAL_DELIVERY_CANDIDATE_IDS,
    FINAL_DELIVERY_SELECTION_STATUS,
    EXPANDED_SELECTION_STATUS,
    DIVERSIFIED_SELECTION_STATUS,
    OHLCV_ALPHA_SELECTION_STATUS,
    STRATEGY_SELECTION_STATUS,
    WORLDQUANT_ALPHA_SELECTION_STATUS,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "dashboard/data/us_equity_research_bundle.json"
PACK = ROOT / "output/research/final_fundamental_research_v1"


def test_bundle_statuses_and_active_only_composite():
    payload = json.loads(BUNDLE.read_text(encoding="utf-8"))["factory_strategy_research"]
    rows = {row["strategy_id"]: row for row in payload["results"]}
    for strategy_id, decision in STRATEGY_SELECTION_STATUS.items():
        factory = rows[strategy_id]["backtest"]["factory_research"]
        assert factory["membership"] == decision["status"]
        assert factory["research_composite_eligible"] is (decision["status"] == "ACTIVE")

    composite = rows["COMBINED_PORTFOLIO_V1"]["backtest"]["factory_research"]["combined_portfolio"]
    active = [strategy_id for strategy_id, value in STRATEGY_SELECTION_STATUS.items() if value["status"] == "ACTIVE"]
    active += [strategy_id for strategy_id, value in FUNDAMENTAL_SELECTION_STATUS.items() if value["status"] == "ACTIVE"]
    active += [strategy_id for strategy_id, value in FINAL_DELIVERY_SELECTION_STATUS.items() if value["status"] == "ACTIVE"]
    active += [strategy_id for strategy_id, value in EXPANDED_SELECTION_STATUS.items() if value["status"] == "ACTIVE"]
    active += [strategy_id for strategy_id, value in OHLCV_ALPHA_SELECTION_STATUS.items() if value["status"] == "ACTIVE"]
    active += [strategy_id for strategy_id, value in DIVERSIFIED_SELECTION_STATUS.items() if value["status"] == "ACTIVE"]
    active += [strategy_id for strategy_id, value in CHALLENGE_SELECTION_STATUS.items() if value["status"] == "ACTIVE" and strategy_id not in EVENT_PANEL_CANDIDATE_IDS]
    active += [strategy_id for strategy_id, value in EVENT_PANEL_SELECTION_STATUS.items() if value["status"] == "ACTIVE"]
    active += [strategy_id for strategy_id, value in WORLDQUANT_ALPHA_SELECTION_STATUS.items() if value["status"] == "ACTIVE"]
    assert composite["constituent_ids"] == active
    assert composite["N"] == len(active)
    assert sum(composite["weights"].values()) == pytest.approx(1.0)
    assert all(weight == pytest.approx(1 / len(active)) for weight in composite["weights"].values())
    assert composite["membership_effective_date"] == "2026-06-15"
    assert composite["prospective_only"] is True


def test_fundamental_candidates_are_research_only_and_trade_log_reconciles():
    payload = json.loads(BUNDLE.read_text(encoding="utf-8"))["factory_strategy_research"]
    rows = {row["strategy_id"]: row for row in payload["results"]}
    summary = pd.read_csv(PACK / "candidate_summary.csv").set_index("strategy_id")
    trades = pd.read_csv(PACK / "trade_log.csv")
    daily = pd.read_csv(PACK / "daily_net_returns.csv")
    for strategy_id in FUNDAMENTAL_RESEARCH_CANDIDATE_IDS:
        backtest = rows[strategy_id]["backtest"]
        expected = FUNDAMENTAL_SELECTION_STATUS[strategy_id]["status"]
        assert backtest["factory_research"]["membership"] == expected
        assert backtest["research_composite_eligible"] is (expected == "ACTIVE")
        assert backtest["live_allocation_approved"] is False
        assert backtest["execution_enabled"] is False
        assert backtest["factory_research"]["data_labels"][:2] == [
            "CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT"
        ]
        assert backtest["factory_research"]["simulated_trade_log"]["execution_enabled"] is False
        assert backtest["holdings"]["last_rebalance_date"]
        trade_cost = trades.loc[trades["strategy_id"] == strategy_id, "estimated_transaction_cost"].sum()
        daily_cost = daily.loc[daily["strategy_id"] == strategy_id, "transaction_cost"].sum()
        assert trade_cost == pytest.approx(daily_cost)
        assert summary.loc[strategy_id, "trade_cost_reconciliation_error"] < 1e-12


def test_final_counts_and_market_proxy_regime_disclosure():
    research = json.loads(BUNDLE.read_text(encoding="utf-8"))["factory_strategy_research"]
    memberships = [row["backtest"]["factory_research"].get("membership") for row in research["results"]]
    assert {status: memberships.count(status) for status in ("ACTIVE", "REPAIR", "ARCHIVED", "DATA_INSUFFICIENT", "REFERENCE_ONLY")} == {
        "ACTIVE": 17, "REPAIR": 35, "ARCHIVED": 24, "DATA_INSUFFICIENT": 4, "REFERENCE_ONLY": 18
    }
    assert research["market_proxy_regime"]["id"] == "MARKET_PROXY_REGIME_V0"
    assert "not a true macro Growth x Inflation model" in research["market_proxy_regime"]["disclosure"]
    assert research["execution_enabled"] is False
    assert research["live_allocation_percent"] == 0.0
