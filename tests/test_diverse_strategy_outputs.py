from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/research/universe_foundation_diverse_strategy_v1"


def test_candidate_output_contract_and_trade_log_reconciliation():
    summary = pd.read_csv(OUTPUT / "candidate_summary.csv")
    daily = pd.read_csv(OUTPUT / "daily_strategy_returns.csv")
    trades = pd.read_csv(OUTPUT / "trade_log.csv")
    assert len(summary) == 11
    assert summary["recommendation"].value_counts().to_dict() == {
        "DATA_INSUFFICIENT": 5, "ACTIVE_CANDIDATE": 3, "ARCHIVED": 2, "REPAIR": 1
    }
    for strategy_id in daily["strategy_id"].unique():
        trade_cost = trades.loc[trades["strategy_id"].eq(strategy_id), "estimated_transaction_cost"].sum()
        daily_cost = daily.loc[daily["strategy_id"].eq(strategy_id), "transaction_cost"].sum()
        assert trade_cost == pytest.approx(daily_cost)


def test_universe_and_market_proxy_manifests_are_explicit():
    manifest = json.loads((OUTPUT / "run_manifest.json").read_text(encoding="utf-8"))
    universes = manifest["universe_manifests"]
    assert universes["SP500_POINT_IN_TIME"]["status"] == "DATA_UNAVAILABLE"
    assert universes["US_BROAD_LIQUID_POINT_IN_TIME"]["source_mode"] == "CURRENT_LISTED_DIAGNOSTIC"
    assert universes["US_SMALL_CAP_LIQUID_POINT_IN_TIME"]["member_count_latest"] == 18
    assert manifest["active_membership_changed"] is False
    assert manifest["combined_portfolio_changed"] is False
    assert manifest["dashboard_changed"] is False
    regimes = pd.read_csv(OUTPUT / "market_proxy_regime_v0.csv")
    assert regimes["regime_id"].eq("MARKET_PROXY_REGIME_V0").all()
    assert regimes["alters_weights"].eq(False).all()
    assert regimes["disclosure"].str.contains("not a true macroeconomic regime").all()
