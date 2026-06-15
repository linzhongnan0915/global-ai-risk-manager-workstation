"""Artifact contract checks for strategy drawer chart series."""

from __future__ import annotations

import json
from pathlib import Path


def test_all_strategies_have_drawer_chart_series():
    artifact_path = Path("output/dashboard_artifact.json")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    missing = []
    for strategy in artifact.get("strategies", []):
        series = (strategy.get("risk_packet") or {}).get("chart_series") or {}
        if not series.get("cumulative_return") or not series.get("drawdown"):
            missing.append(strategy["strategy_id"])
        assert "rolling_63d_sharpe" in series or "rolling_sharpe" in series or series.get("rolling_63d_sharpe") is not None
    assert not missing, f"strategies missing chart series: {missing}"


def test_literature_backtests_expose_gross_net_return_series():
    artifact = json.loads(Path("output/dashboard_artifact.json").read_text(encoding="utf-8"))
    results = artifact.get("literature_strategy_backtests", {}).get("results") or []
    assert results
    for row in results:
        rs = (row.get("backtest") or {}).get("return_series") or {}
        assert rs.get("gross_returns"), row.get("backtest", {}).get("strategy_id")
        assert rs.get("net_returns"), row.get("backtest", {}).get("strategy_id")
