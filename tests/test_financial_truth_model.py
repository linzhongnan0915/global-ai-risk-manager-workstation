"""Regression tests for P0-A financial truth model."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.allocation.rebalance_simulation import build_simulation_context
from src.reporting.artifact_generator import (
    _cash_semantics,
    _since_investment_metrics,
    generate_dashboard_artifact,
)
from src.risk.limits import evaluate_residual_cash_limit, evaluate_strategy_limits
from src.risk.metric_availability import build_operating_period_risk, wrap_metric
from src.risk.risk_status_summary import build_risk_status_summary, enrich_check


def test_data_classification_in_generated_artifact():
    artifact_path = Path("output/dashboard_artifact.json")
    if not artifact_path.exists():
        generate_dashboard_artifact(
            Path("data/config/strategy_registry.json"),
            artifact_path,
        )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    classification = artifact["data_classification"]
    assert classification["is_live_portfolio_data"] is False
    assert classification["portfolio_mode"] == "prototype_model_portfolio"
    assert "Not live positions or fills" in classification["disclosure"]
    assert artifact["build_metadata"]["build_id"].startswith("p0a-")


def test_two_observation_operating_metrics_unavailable():
    operating = build_operating_period_risk(
        {"A": [0.001, -0.002]},
        {"A": 1.0},
        observations=2,
        start_date="2026-06-04",
        end_date="2026-06-05",
        daily_return=-0.002,
        cumulative_return=-0.001,
    )
    assert operating["metrics"]["portfolio_sharpe"]["available"] is False
    assert operating["metrics"]["portfolio_volatility"]["available"] is False
    assert operating["metrics"]["portfolio_var_99"]["available"] is False
    assert operating["metrics"]["portfolio_expected_shortfall_95"]["available"] is False
    assert operating["metrics"]["portfolio_max_drawdown"]["available"] is True
    assert operating["pnl"]["daily_return"]["available"] is True


def test_sufficient_history_metrics_available():
    returns = [0.001] * 100
    operating = build_operating_period_risk(
        {"A": returns},
        {"A": 1.0},
        observations=100,
        start_date="2026-01-01",
        end_date="2026-06-01",
        daily_return=0.001,
        cumulative_return=0.05,
    )
    assert operating["metrics"]["portfolio_sharpe"]["available"] is True
    assert operating["metrics"]["portfolio_volatility"]["available"] is True


def test_canonical_status_counts_each_check_once():
    check_a = enrich_check(
        {"limit_id": "A", "metric": "x", "status": "breach", "action": "Review", "current_value": 1, "breach_threshold": 0.5},
        scope="factor",
        subject_id="portfolio",
        allocation_relevance="allocated_model",
        applicability="allocated_model",
    )
    summary = build_risk_status_summary(
        portfolio_checks=[],
        allocated_strategy_checks=[],
        research_quality_checks=[],
        factor_checks=[check_a, dict(check_a)],
        scenario_checks=[],
        correlation_checks=[],
        rebalance_checks=[],
        residual_cash_checks=[],
        data_quality_checks=[],
        governance_checks=[],
    )
    assert summary["headline"]["blocking_breaches"] == 1
    assert "factor" in summary["headline"]["included_scopes"]


def test_zero_allocation_strategy_skips_live_monitoring():
    result = evaluate_strategy_limits({"strategy_id": "S1", "current_weight": 0.0, "risk_packet": {}})
    assert result["applicability"] == "not_applicable"
    assert result["checks"] == []


def test_cash_semantics_separate_proxy_and_residual():
    semantics = _cash_semantics({"cash": 0.39}, invested_weight=1.0)
    assert semantics["treasury_bill_proxy_exposure"] == pytest.approx(0.39)
    assert semantics["portfolio_residual_cash_weight"] == pytest.approx(0.0)

    residual_status = evaluate_residual_cash_limit(0.05)
    assert residual_status["checks"][0]["current_value"] == pytest.approx(0.95)

    full_invested = evaluate_residual_cash_limit(1.0)
    assert full_invested["checks"][0]["current_value"] == pytest.approx(0.0)
    assert full_invested["checks"][0]["status"] == "ok"


def test_since_investment_max_drawdown_uses_return_path():
    backtest = {
        "return_series": {
            "dates": ["2026-06-04", "2026-06-05", "2026-06-06"],
            "net_returns": [0.0, -0.10, 0.05],
        }
    }
    metrics = _since_investment_metrics(backtest, "2026-06-04", weight=1.0, capital=1_000_000)
    assert metrics["max_drawdown"]["available"] is True
    assert metrics["max_drawdown"]["value"] == pytest.approx(-0.10, rel=1e-6, abs=1e-6)


def test_simulation_reports_residual_cash_consistently():
    context = build_simulation_context(
        {"A": [0.001, 0.002], "B": [0.001, 0.002]},
        [{"strategy_id": "A", "factor_exposure": {"latest": {}}}, {"strategy_id": "B", "factor_exposure": {"latest": {}}}],
        {"A": 0.5, "B": 0.45},
        {"A": 0.5, "B": 0.45},
        1_000_000,
    )
    official = context["official_optimizer"]
    assert official["cash_weight"] == pytest.approx(0.05, rel=1e-6)


def test_wrap_metric_includes_observation_metadata():
    wrapped = wrap_metric(None, "sharpe", observations=2)
    assert wrapped["available"] is False
    assert wrapped["observations"] == 2
    assert wrapped["minimum_observations"] == 63
