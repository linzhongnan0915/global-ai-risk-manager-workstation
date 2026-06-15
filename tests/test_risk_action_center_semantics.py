"""Acceptance tests for Risk Action Center display semantics."""

from __future__ import annotations

import json
from pathlib import Path

from src.risk.risk_action_display import (
    compute_utilization,
    display_action,
    display_gap,
    display_status,
    include_in_current_model,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _factor_check(metric: str) -> dict:
    artifact = json.loads((PROJECT_ROOT / "output" / "dashboard_artifact.json").read_text(encoding="utf-8"))
    checks = artifact["risk_status_summary"]["scopes"]["factor"]["checks"]
    return next(check for check in checks if check["metric"] == metric)


def _scenario_check(name: str) -> dict:
    artifact = json.loads((PROJECT_ROOT / "output" / "dashboard_artifact.json").read_text(encoding="utf-8"))
    checks = artifact["risk_status_summary"]["scopes"]["scenario"]["checks"]
    return next(check for check in checks if check["metric"] == name)


def test_upper_limit_acceptance_statuses():
    beta = _factor_check("equity_beta")
    assert round(beta["current_value"], 3) == 0.154
    assert beta["breach_threshold"] == 0.15
    assert display_status({**beta, "scope": "factor"}) == "breach"

    credit = _factor_check("credit_spread")
    assert round(credit["current_value"], 3) == 0.113
    assert credit["breach_threshold"] == 0.1
    assert display_status({**credit, "scope": "factor"}) == "breach"

    duration = _factor_check("rates_duration")
    assert round(duration["current_value"], 3) == 0.113
    assert duration["breach_threshold"] == 0.12
    assert display_status({**duration, "scope": "factor"}) == "warning"


def test_normal_metrics_excluded_from_current_model():
    concentration = _factor_check("factor_herfindahl")
    assert display_status({**concentration, "scope": "factor"}) == "ok"
    assert include_in_current_model({**concentration, "scope": "factor"}) is False

    cash = _factor_check("cash_exposure")
    assert round(cash["current_value"], 2) == 0.39
    assert cash["breach_threshold"] == 0.6
    assert display_status({**cash, "scope": "factor"}) == "ok"
    assert include_in_current_model({**cash, "scope": "factor"}) is False


def test_scenario_within_limit_is_normal():
    equity = _scenario_check("Equity -5%")
    assert round(equity["current_value"], 3) == -0.009
    assert equity["breach_threshold"] == -0.0125
    assert round(compute_utilization({**equity, "scope": "scenario"}), 3) == 0.735
    assert display_status({**equity, "scope": "scenario"}) == "ok"
    assert include_in_current_model({**equity, "scope": "scenario"}) is False


def test_not_modeled_rows():
    for metric in ("volatility", "short_vol"):
        check = _factor_check(metric)
        assert check["current_value"] is None
        assert display_status({**check, "scope": "factor"}) == "not_modeled"
        assert display_action({**check, "scope": "factor"}) == "Review model coverage"
        assert include_in_current_model({**check, "scope": "factor"}) is True


def test_rolling_sharpe_uses_gap_not_utilization():
    artifact = json.loads((PROJECT_ROOT / "output" / "dashboard_artifact.json").read_text(encoding="utf-8"))
    checks = artifact["risk_status_summary"]["scopes"]["allocated_strategy_live"]["checks"]
    warning = next(
        check
        for check in checks
        if check["metric"] == "latest_63d_rolling_sharpe" and check["status"] == "warning"
    )
    assert compute_utilization({**warning, "scope": "allocated_strategy_live"}) is None
    gap = display_gap({**warning, "scope": "allocated_strategy_live"})
    assert gap == warning["current_value"] - warning["breach_threshold"]
