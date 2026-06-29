import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shadow_bundle_dashboard_contract():
    bundle = json.loads((ROOT / "dashboard/data/shadow_live_bundle.json").read_text(encoding="utf-8"))
    shadow = bundle["shadow_live"]
    assert bundle["live_capital_percent"] == 0
    assert bundle["live_allocation_approved"] is False
    assert bundle["execution_enabled"] is False
    assert len(shadow["strategy_summary"]) == 16
    assert shadow["runner_mode"] == "RAW DATA SIGNAL RUNNER"
    assert shadow["accepted_series_historical_reference_only"] is True
    assert shadow["configured_strategy_count"] == shadow["successful_strategy_count"] == 17
    assert shadow["partial_strategy_count"] == shadow["unavailable_strategy_count"] == 0
    assert shadow["entry_eligibility_universe_size"] == 229
    assert shadow["operational_pricing_universe_size"] == 301
    assert shadow["segments"]["transition_nav"] > 1_000_000
    assert shadow["correlation"]["status"] == "NOT ENOUGH LIVE HISTORY"
    assert shadow["correlation"]["observations"] < 20
    assert shadow["correlation"]["minimum_observations"] == 20
    assert shadow["previous_active_count"] == 16
    assert shadow["current_active_count"] == 17
    assert shadow["membership_effective_date"] == "2026-06-15"
    assert shadow["strategy_details"]["WQ_ALPHA_018"]["research_metrics"]["net_sharpe"] > 0.52
    assert shadow["reconciliation"]["date_effective_sleeve_weights"] is True
    assert shadow["reconciliation"]["trade_costs_equal_strategy_ledger_costs"] is True


def test_dashboard_foundation_uses_canonical_operational_contract():
    index = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    for marker in (
        "Foundation Preview",
        "foundation-components.js",
        "foundation-app.js",
    ):
        assert marker in index
    for marker in (
        "Canonical Data Foundation",
        "/api/operational-snapshot",
        "Simulated, no live fill",
        "Approved membership",
        "Unavailable",
        "DERIVED_COMPLETE",
        "Derived Combined Strategy Ledger",
        "Derived from ordinary strategy net-return ledgers",
        "post-admission proposal",
        "Top-Level Active",
        "pending / inactive rows separated",
        "Intraday Estimated NAV",
        "Intraday Estimated P&L",
        "Latest Delayed Price As-Of",
        "Portfolio Daily Date",
        "Portfolio Daily Source",
        "<b>Date</b>",
        "<b>Source</b>",
        "<b>NAV</b>",
        "Daily P&L",
        "Daily Return",
        "<b>Drawdown</b>",
        "Intraday Est. P&L",
        "not official ledger",
    ):
        assert marker in app
