"""Focused tests for the Combined Portfolio research platform."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.strategies.composite_membership import equal_composite_weight
from src.strategies.platform_registry import COMPOSITE_ID, RAPID_BACKTEST_IDS
from src.strategies.rapid_20plus1 import build_equal_weight_composite


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts/rapid_20plus1"
BUNDLE_PATH = PROJECT_ROOT / "dashboard/data/us_equity_research_bundle.json"


@pytest.mark.skipif(not (ARTIFACT_ROOT / "strategy_leaderboard.csv").exists(), reason="rapid artifacts missing")
def test_leaderboard_splits_active_and_reference():
    board = pd.read_csv(ARTIFACT_ROOT / "strategy_leaderboard.csv")
    active = board.loc[board["membership"] == "ACTIVE"]
    reference = board.loc[board["membership"] == "REFERENCE_ONLY"]
    assert len(active) + len(reference) == len(RAPID_BACKTEST_IDS)
    assert (active["sharpe"] > 0).all()
    assert set(active["strategy_id"]).issubset(set(RAPID_BACKTEST_IDS))
    assert (active["net_return"] > 0).all()


@pytest.mark.skipif(not (ARTIFACT_ROOT / "correlation_matrix.csv").exists(), reason="rapid artifacts missing")
def test_active_correlation_matrix_shape():
    board = pd.read_csv(ARTIFACT_ROOT / "strategy_leaderboard.csv")
    active_count = int((board["membership"] == "ACTIVE").sum())
    corr = pd.read_csv(ARTIFACT_ROOT / "correlation_matrix.csv", index_col=0)
    assert corr.shape == (active_count, active_count)
    assert (corr.values.diagonal() == 1).all()


@pytest.mark.skipif(not (ARTIFACT_ROOT / "combined_portfolio_summary.json").exists(), reason="combined portfolio missing")
def test_combined_portfolio_matches_active_member_count():
    summary = json.loads((ARTIFACT_ROOT / "combined_portfolio_summary.json").read_text(encoding="utf-8"))
    board = pd.read_csv(ARTIFACT_ROOT / "strategy_leaderboard.csv")
    active_count = int((board["membership"] == "ACTIVE").sum())
    assert summary["N"] == active_count
    assert active_count >= 1
    assert summary["strategy_id"] == COMPOSITE_ID
    assert pytest.approx(sum(summary["constituent_weights"].values())) == 1.0
    assert pytest.approx(summary["equal_weight"]) == equal_composite_weight(active_count)
    assert summary.get("dynamic_membership") is True


@pytest.mark.skipif(not (ARTIFACT_ROOT / "combined_portfolio_evidence_manifest.json").exists(), reason="evidence missing")
def test_evidence_manifest_has_charts_and_limits():
    manifest = json.loads((ARTIFACT_ROOT / "combined_portfolio_evidence_manifest.json").read_text(encoding="utf-8"))
    assert manifest["composite_id"] == COMPOSITE_ID
    assert manifest["governance_limits"]["allocation_approved"] is False
    assert "combined_portfolio_equity_drawdown.png" in manifest["charts"]


@pytest.mark.skipif(not BUNDLE_PATH.exists(), reason="dashboard bundle missing")
def test_bundle_has_all_underlying_plus_composite():
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    results = payload["factory_strategy_research"]["results"]
    assert len(results) == len(RAPID_BACKTEST_IDS) + 1


def test_combined_portfolio_weight_math_unit():
    columns = ["A", "B", "C", "D"]
    data = {col: [0.001, 0.002, -0.001] for col in columns}
    gross = pd.DataFrame(data, index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]))
    net = gross - 0.0001
    _, summary = build_equal_weight_composite(gross, net)
    assert summary["N"] == 4
    assert pytest.approx(summary["equal_weight"]) == 0.25
