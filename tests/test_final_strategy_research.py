from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_final_strategy_research import legacy_diagnostics

ROOT = Path(__file__).resolve().parents[1]
FUNDAMENTAL_ROOT = ROOT / "output/research/final_fundamental_research_v1"
FINAL_ROOT = ROOT / "output/research/final_strategy_research_v1"


def test_legacy_duplicate_and_diversifier_decisions_use_daily_returns():
    dates = pd.bdate_range("2024-01-02", periods=8)
    returns = pd.DataFrame(
        {
            strategy_id: [0.001, -0.001, 0.002, -0.001, 0.001, 0.0, 0.001, -0.001]
            for strategy_id in (
                "C2A2_004", "C2A2_020", "C3A1_001", "C3A1_002", "C3A1_003", "C3A1_004",
                "C3A1_005", "C3A1_006", "C3A1_012", "C3A1_013", "C3A1_015", "C3A2_008",
            )
        },
        index=dates,
    )
    returns["C3A2_009"] = [0.001, 0.001, -0.001, -0.001, 0.001, -0.001, 0.001, -0.001]
    rows = {
        strategy_id: {
            "backtest": {
                "net_metrics": {"cumulative_return": 0.1, "sharpe": 0.3, "max_drawdown": -0.1},
                "turnover": {"annualized_turnover": 2.0, "total_cost_drag": 0.01},
            }
        }
        for strategy_id in returns
    }
    decisions = legacy_diagnostics(rows, returns).set_index("strategy_id")

    assert decisions.loc["C3A2_009", "recommendation"] == "REPAIR"
    assert decisions.loc["C3A1_005", "recommendation"] == "REPAIR"
    assert decisions.loc["C3A1_015", "recommendation"] == "ACTIVE"


def test_final_research_outputs_are_research_only_and_reconciled():
    manifest = json.loads((FINAL_ROOT / "run_manifest.json").read_text(encoding="utf-8"))
    recommendations = pd.read_csv(FINAL_ROOT / "final_recommendations.csv")
    regimes = pd.read_csv(FINAL_ROOT / "market_proxy_regime_v0.csv")
    trades = pd.read_csv(FUNDAMENTAL_ROOT / "trade_log.csv")
    daily = pd.read_csv(FUNDAMENTAL_ROOT / "daily_net_returns.csv")

    assert manifest["registry_updated"] is True
    assert manifest["combined_portfolio_updated"] is True
    assert manifest["dashboard_updated"] is True
    assert manifest["live_allocation_percent"] == 0.0
    assert manifest["execution_enabled"] is False
    assert recommendations.groupby("recommendation").size().to_dict() == {
        "ACTIVE": 9, "ARCHIVED": 4, "REPAIR": 12
    }
    assert set(regimes["regime"]) == {
        "MARKET_PROXY_GROWTH_DOWN_INFLATION_DOWN",
        "MARKET_PROXY_GROWTH_DOWN_INFLATION_UP",
        "MARKET_PROXY_GROWTH_UP_INFLATION_DOWN",
        "MARKET_PROXY_GROWTH_UP_INFLATION_UP",
    }
    for strategy_id in daily["strategy_id"].unique():
        trade_cost = trades.loc[trades["strategy_id"].eq(strategy_id), "estimated_transaction_cost"].sum()
        daily_cost = daily.loc[daily["strategy_id"].eq(strategy_id), "transaction_cost"].sum()
        assert trade_cost == pytest.approx(daily_cost)
