import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD_PROXY_NAMES = {
    "Liquid Alternative Factor Premia Clone",
    "Business-Cycle Regime Allocation",
    "High-Volatility Regime Defensive Switch",
    "Managed Futures Trend Proxy",
    "Convertible Arbitrage Proxy",
    "Tail Hedge Crisis Sleeve",
}


def _bundle():
    return json.loads((ROOT / "dashboard/data/shadow_live_bundle.json").read_text(encoding="utf-8"))


def test_combined_portfolio_is_date_effective_and_reconciled():
    shadow = _bundle()["shadow_live"]
    ledger = shadow["portfolio_ledger"]
    timeline = shadow["membership_timeline"]

    assert ledger
    assert all(row["active_count"] == 16 for row in ledger if row["date"] < "2026-06-15")
    assert all(abs(row["equal_strategy_weight"] * row["active_count"] - 1.0) < 1e-9 for row in ledger)
    assert timeline[0]["effective_date"] == "2026-06-15"
    assert timeline[0]["previous_active_count"] == 16
    assert timeline[0]["new_active_count"] == 17
    assert abs(timeline[0]["new_equal_weight"] * timeline[0]["new_active_count"] - 1.0) < 1e-8
    assert timeline[0]["strategy_added"] == "WQ_ALPHA_018"


def test_combined_portfolio_contains_only_current_underlying_strategies():
    shadow = _bundle()["shadow_live"]
    executed_ids = {row["strategy_id"] for row in shadow["strategy_summary"]}
    pending_ids = set(shadow["strategy_details"])
    accepted_ids = executed_ids | pending_ids

    assert len(executed_ids) == 16
    assert len(accepted_ids) == 17
    assert "WQ_ALPHA_018" in pending_ids
    assert "COMBINED_PORTFOLIO" not in accepted_ids
    assert not (OLD_PROXY_NAMES & accepted_ids)
    assert sum(row["strategy_id"] == "WQ_ALPHA_018" for row in shadow["pending_targets"]) == 88
    assert not any(row["strategy_id"] == "WQ_ALPHA_018" for row in shadow["trades"])


def test_production_render_path_is_operational_bundle_only():
    app = (ROOT / "dashboard/app.js").read_text(encoding="utf-8")
    index = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")

    assert "Combined Portfolio · Date-Effective ACTIVE Membership" in app
    assert "canonicalOperationalArtifact(shadowBundle)" in app
    init = app[app.rfind("async function init()") :]
    assert "loadArtifact()" not in init
    assert "loadLiveOverlay()" not in init
    assert "loadUsEquityResearchBundle()" not in init
    assert "installLiveControls" not in init
    assert "Monitored <strong>" not in init
    assert "intradayCadenceSelect" not in index
    assert "refreshLiveData" not in index


def test_production_navigation_excludes_legacy_proxy_pages():
    app = (ROOT / "dashboard/app.js").read_text(encoding="utf-8")
    nav = app[app.index("const NAV_SECTIONS") : app.index("const fallbackArtifact")]

    for visible in ("Command Center", "Strategies", "Daily Performance", "Trade Log", "Correlation", "Strategy Detail"):
        assert visible in nav
    for hidden in ("Allocation", "Proxy Loadings", "Workflow", "Daily Report", "Market & Macro"):
        assert hidden not in nav
